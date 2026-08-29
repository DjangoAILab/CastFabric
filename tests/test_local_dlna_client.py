import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from miair.config import Speaker
from miair.const import AVTRANSPORT_URN, RENDERING_CONTROL_URN
from miair.dlna.client import LocalDLNAClient, _parse_ssdp_headers
from miair.speaker import SpeakerController


class LocalDLNAClientTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self):
        return LocalDLNAClient(
            "http://192.0.2.10:1958/",
            {
                AVTRANSPORT_URN: "http://192.0.2.10:1958/av/control.xml",
                RENDERING_CONTROL_URN: "http://192.0.2.10:1958/rc/control.xml",
            },
        )

    def test_ssdp_headers_are_case_insensitive(self):
        headers = _parse_ssdp_headers(
            b"HTTP/1.1 200 OK\r\nUSN: uuid:device::type\r\nLocation: http://host/\r\n\r\n"
        )
        self.assertEqual(headers["usn"], "uuid:device::type")
        self.assertEqual(headers["location"], "http://host/")

    async def test_play_sets_uri_before_play(self):
        client = self.make_client()
        client._soap = AsyncMock(return_value={})

        self.assertTrue(await client.play_url("http://gateway/media?a=1&b=2"))

        self.assertEqual(client._soap.await_count, 2)
        set_uri, play = client._soap.await_args_list
        self.assertEqual(set_uri.args[1], "SetAVTransportURI")
        self.assertEqual(
            set_uri.args[2]["CurrentURI"], "http://gateway/media?a=1&b=2"
        )
        self.assertEqual(play.args[1], "Play")

    async def test_transport_state_maps_to_existing_speaker_status(self):
        client = self.make_client()
        client._soap = AsyncMock(
            return_value={"CurrentTransportState": "PAUSED_PLAYBACK"}
        )
        client.get_volume = AsyncMock(return_value=16)

        self.assertEqual(await client.get_status(), {"status": 2, "volume": 16})

    async def test_speaker_controller_prefers_local_renderer_without_cloud(self):
        local = SimpleNamespace(play_url=AsyncMock(return_value=True))
        mina = SimpleNamespace(play_by_url=AsyncMock())
        auth = SimpleNamespace(ensure_login=AsyncMock(), mina_service=mina)
        controller = SpeakerController(
            Speaker(
                did="did",
                device_id="device-id",
                hardware="M01",
                compatibility_mode=True,
            ),
            auth,
            local_dlna=local,
        )

        self.assertTrue(await controller.play_url("http://gateway/media"))
        local.play_url.assert_awaited_once_with("http://gateway/media")
        auth.ensure_login.assert_not_awaited()
        mina.play_by_url.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
