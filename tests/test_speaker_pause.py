import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from miair.config import Speaker
from miair.speaker import SpeakerController


def mina_response(device_code=0, proxy_code=0):
    return {"code": proxy_code, "data": {"code": device_code}}


class SpeakerPauseTests(unittest.IsolatedAsyncioTestCase):
    def make_controller(self, hardware, compatibility_mode):
        mina_service = SimpleNamespace(
            player_pause=AsyncMock(return_value=mina_response()),
            player_stop=AsyncMock(return_value=mina_response()),
        )
        auth = SimpleNamespace(
            ensure_login=AsyncMock(),
            mina_service=mina_service,
        )
        speaker = Speaker(
            did="test-did",
            device_id="test-device-id",
            hardware=hardware,
            compatibility_mode=compatibility_mode,
        )
        return SpeakerController(speaker, auth), mina_service

    async def test_m01_uses_stop_while_keeping_compatibility_mode(self):
        controller, mina = self.make_controller("M01", True)

        self.assertTrue(await controller.pause())

        mina.player_stop.assert_awaited_once_with("test-device-id")
        mina.player_pause.assert_not_awaited()
        self.assertFalse(controller._should_use_music_api())

    async def test_xmyx01jy_uses_stop_while_keeping_compatibility_mode(self):
        controller, mina = self.make_controller("XMYX01JY", True)

        self.assertTrue(await controller.pause())

        mina.player_stop.assert_awaited_once_with("test-device-id")
        mina.player_pause.assert_not_awaited()

    async def test_regular_compatibility_device_still_uses_pause(self):
        controller, mina = self.make_controller("GENERIC", True)

        self.assertTrue(await controller.pause())

        mina.player_pause.assert_awaited_once_with("test-device-id")
        mina.player_stop.assert_not_awaited()

    async def test_non_compatibility_device_still_uses_stop(self):
        controller, mina = self.make_controller("X08C", False)

        self.assertTrue(await controller.pause())

        mina.player_stop.assert_awaited_once_with("test-device-id")
        mina.player_pause.assert_not_awaited()

    async def test_device_error_is_reported_as_pause_failure(self):
        controller, mina = self.make_controller("M01", True)
        mina.player_stop.return_value = mina_response(device_code=123)

        self.assertFalse(await controller.pause())

    async def test_proxy_error_is_reported_as_pause_failure(self):
        controller, mina = self.make_controller("M01", True)
        mina.player_stop.return_value = mina_response(proxy_code=401)

        self.assertFalse(await controller.pause())


if __name__ == "__main__":
    unittest.main()
