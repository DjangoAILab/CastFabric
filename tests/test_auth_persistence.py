import json
import os
import stat
import tempfile
import unittest
import asyncio
from unittest.mock import AsyncMock, patch

import aiohttp
from miservice import MiAccount

from miair.auth import (
    AtomicTokenStore,
    AuthManager,
    PersistentMiAccount,
    parse_cookie_string,
)
from miair.config import Config


def token(user_id="100200", pass_token="rotated-token", device_id="A" * 16):
    return {
        "userId": user_id,
        "passToken": pass_token,
        "deviceId": device_id,
        "micoapi": ["ssecurity", "service-token"],
    }


class AtomicTokenStoreTests(unittest.TestCase):
    def test_failed_save_preserves_last_known_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, ".mi.token")
            store = AtomicTokenStore(path)
            expected = token()

            store.save_token(expected)
            store.save_token()

            self.assertEqual(store.load_token(), expected)
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)

    def test_cookie_parser_preserves_browser_device_id(self):
        parsed = parse_cookie_string(
            "userId=100200; passToken=token; deviceId=wb_browser-device"
        )
        self.assertEqual(parsed["deviceId"], "wb_browser-device")


class AuthManagerPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_login_is_single_flight_and_rate_limited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Config(
                hostname="127.0.0.1",
                conf_path=temp_dir,
                cookie="userId=100200; passToken=bootstrap-token",
                mi_did="123",
            )
            manager = AuthManager(config)
            try:
                async def fail_once():
                    await asyncio.sleep(0.01)
                    return False

                manager._login_once = AsyncMock(side_effect=fail_once)

                with patch.object(
                    PersistentMiAccount, "login", new=AsyncMock(return_value=False)
                ):
                    results = await asyncio.gather(
                        *(manager.login() for _ in range(5))
                    )

                self.assertEqual(results, [False] * 5)
                manager._login_once.assert_awaited_once()
                self.assertGreater(manager._next_login_attempt, 0)
            finally:
                await manager.close()

    async def test_failed_login_exposes_safe_actionable_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Config(
                hostname="127.0.0.1",
                conf_path=temp_dir,
                cookie="userId=100200; passToken=bootstrap-token",
                mi_did="123",
            )
            manager = AuthManager(config)
            manager._login_once = AsyncMock(return_value=False)
            manager.last_error_code = "70016"
            manager.last_error_message = manager._friendly_error_message("70016")

            await manager.login()

            status = manager.get_auth_status()
            self.assertEqual(status["auth_state"], "cooldown")
            self.assertEqual(status["auth_error_code"], "70016")
            self.assertIn("micoapi", status["auth_error_message"])
            self.assertGreater(status["auth_retry_after"], 0)

    async def test_matching_complete_stored_token_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stored = token(pass_token="rotated-token")
            token_path = os.path.join(temp_dir, ".mi.token")
            with open(token_path, "w", encoding="utf-8") as handle:
                json.dump(stored, handle)

            config = Config(
                hostname="127.0.0.1",
                conf_path=temp_dir,
                cookie="userId=100200; passToken=stale-bootstrap",
                mi_did="123",
            )
            manager = AuthManager(config)
            try:
                with patch.object(
                    MiAccount, "login", new=AsyncMock(return_value=False)
                ) as login:
                    await manager.login()

                self.assertTrue(manager.is_logged_in())
                self.assertEqual(manager.account.token, stored)
                login.assert_not_awaited()
                self.assertEqual(
                    stat.S_IMODE(os.stat(token_path).st_mode), 0o600
                )
            finally:
                await manager.close()

    async def test_cookie_bootstrap_is_really_exchanged_for_micoapi(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Config(
                hostname="127.0.0.1",
                conf_path=temp_dir,
                cookie="userId=100200; passToken=bootstrap-token",
                mi_did="123",
            )
            manager = AuthManager(config)
            try:
                login = AsyncMock(return_value=False)
                with patch.object(MiAccount, "login", new=login):
                    await manager.login()

                login.assert_awaited()
                self.assertFalse(manager.is_logged_in())
            finally:
                await manager.close()


class PersistentMiAccountTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_tries_new_bootstrap_without_losing_old_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, ".mi.token")
            store = AtomicTokenStore(path)
            old = token(pass_token="old-token")
            store.save_token(old)
            session = aiohttp.ClientSession()
            try:
                account = PersistentMiAccount(
                    session,
                    "",
                    "",
                    token_store=store,
                    bootstrap_tokens=[
                        {
                            "userId": "100200",
                            "passToken": "new-token",
                            "deviceId": old["deviceId"],
                        }
                    ],
                )
                seen = []

                async def fake_login(instance, sid):
                    seen.append(instance.token["passToken"])
                    if instance.token["passToken"] == "old-token":
                        instance.token = None
                        instance.token_store.save_token()
                        return False
                    instance.token = token(pass_token="new-token")
                    instance.token_store.save_token(instance.token)
                    return True

                with patch.object(MiAccount, "login", new=fake_login):
                    self.assertTrue(await account.login("micoapi"))

                self.assertEqual(seen, ["old-token", "new-token"])
                self.assertEqual(store.load_token()["passToken"], "new-token")
            finally:
                await session.close()

    async def test_mi_request_restores_refresh_seed_after_dependency_clears_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AtomicTokenStore(os.path.join(temp_dir, ".mi.token"))
            stored = token(pass_token="rotated-token")
            store.save_token(stored)
            session = aiohttp.ClientSession()
            try:
                account = PersistentMiAccount(
                    session,
                    "",
                    "",
                    token_store=store,
                    bootstrap_tokens=[],
                )

                async def fake_request(
                    instance, sid, url, data, headers, relogin=True
                ):
                    if relogin:
                        instance.token = None
                        return await instance.mi_request(
                            sid, url, data, headers, False
                        )
                    return copy_token(instance.token)

                with patch.object(MiAccount, "mi_request", new=fake_request):
                    recovered = await account.mi_request(
                        "micoapi", "https://example.invalid", None, {}
                    )

                self.assertEqual(recovered["passToken"], "rotated-token")
                self.assertNotIn("micoapi", recovered)
            finally:
                await session.close()


def copy_token(value):
    return json.loads(json.dumps(value))


if __name__ == "__main__":
    unittest.main()
