import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from miair.config import Speaker
from miair.speaker import SpeakerController


class SpeakerPlayUrlTests(unittest.IsolatedAsyncioTestCase):
    def make_controller(self, compatibility_mode):
        mina_service = SimpleNamespace(
            play_by_url=AsyncMock(
                return_value={"code": 0, "data": {"code": 0}}
            ),
            play_by_music_url=AsyncMock(
                return_value={"code": 0, "data": {"code": 0}}
            ),
        )
        auth = SimpleNamespace(
            ensure_login=AsyncMock(),
            mina_service=mina_service,
        )
        speaker = Speaker(
            did="test-did",
            device_id="test-device-id",
            hardware="M01",
            compatibility_mode=compatibility_mode,
        )
        return SpeakerController(speaker, auth), mina_service

    async def test_compatibility_path_forwards_experimental_play_type(self):
        controller, mina = self.make_controller(compatibility_mode=True)

        self.assertTrue(await controller.play_url("http://stream", play_type=1))

        mina.play_by_url.assert_awaited_once_with(
            "test-device-id", "http://stream", _type=1
        )
        mina.play_by_music_url.assert_not_awaited()

    async def test_default_type_remains_two_for_other_protocols(self):
        controller, mina = self.make_controller(compatibility_mode=True)

        self.assertTrue(await controller.play_url("http://stream"))

        mina.play_by_url.assert_awaited_once_with(
            "test-device-id", "http://stream", _type=2
        )

    async def test_music_api_path_forwards_experimental_play_type(self):
        controller, mina = self.make_controller(compatibility_mode=False)

        self.assertTrue(await controller.play_url("http://stream", play_type=0))

        call = mina.play_by_music_url.await_args
        self.assertEqual(call.args, ("test-device-id", "http://stream"))
        self.assertEqual(call.kwargs["_type"], 0)
        mina.play_by_url.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
