import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from miair.app import MiAir
from miair.config import Config, Speaker


class AuthenticationRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_speaker_is_advertised_when_cloud_auth_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Config(
                hostname="127.0.0.1",
                conf_path=temp_dir,
                cookie="userId=100200; passToken=bootstrap-token",
                mi_did="123",
                auto_restart=True,
                enable_miplay=False,
                speakers={
                    "123": Speaker(
                        did="123",
                        device_id="cached-device-id",
                        name="Cached speaker",
                    )
                },
            )
            config.speakers["123"].ensure_udn()
            app = MiAir(config)
            app.auth = SimpleNamespace(
                login=AsyncMock(return_value=False),
                is_logged_in=Mock(return_value=False),
            )
            app.speaker_manager.auth = app.auth
            app._schedule_auth_retry = Mock()

            with (
                patch("miair.app.SSDPServer") as ssdp_cls,
                patch("miair.app.DeviceServer") as device_cls,
                patch.object(app, "_start_airplay_for_speakers", AsyncMock()),
            ):
                ssdp_cls.return_value.start = AsyncMock()
                device_cls.return_value.start = AsyncMock()
                await app._start_dlna_services()

            app._schedule_auth_retry.assert_called_once()
            self.assertTrue(app.dlna_running)
            self.assertEqual(len(app.renderers), 1)
            self.assertIn("123", app.speaker_manager.controllers)

    def test_auth_retry_backoff_is_bounded(self):
        self.assertEqual(MiAir.AUTH_RETRY_DELAYS, (30, 120, 300, 900))


if __name__ == "__main__":
    unittest.main()
