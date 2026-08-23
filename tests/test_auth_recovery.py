import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from miair.app import MiAir
from miair.config import Config


class AuthenticationRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_device_list_schedules_in_process_retry(self):
        config = Config(
            hostname="127.0.0.1",
            cookie="userId=100200; passToken=bootstrap-token",
            mi_did="123",
            auto_restart=True,
        )
        app = MiAir(config)
        app.auth = SimpleNamespace(
            login=AsyncMock(),
            is_logged_in=Mock(return_value=True),
            get_device_list=AsyncMock(return_value=[]),
        )
        app.speaker_manager = SimpleNamespace(controllers={})
        app._schedule_auth_retry = Mock()

        await app._start_dlna_services()

        app._schedule_auth_retry.assert_called_once()
        self.assertFalse(app.dlna_running)

    def test_auth_retry_backoff_is_bounded(self):
        self.assertEqual(MiAir.AUTH_RETRY_DELAYS, (30, 120, 300, 900))


if __name__ == "__main__":
    unittest.main()
