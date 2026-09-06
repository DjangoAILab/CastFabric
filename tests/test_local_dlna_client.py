import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp

from miair.config import Speaker
from miair.const import AVTRANSPORT_URN, RENDERING_CONTROL_URN
from miair.dlna.client import LocalDLNAClient, _parse_ssdp_headers, _parse_transport_time
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

        self.assertEqual(await client.get_status(), {"status": 2, "volume": 16, "seek_supported": False})

    async def test_seek_uses_dlna_relative_time(self):
        client = self.make_client()
        client._soap = AsyncMock(return_value={})

        self.assertTrue(await client.seek(125))

        client._soap.assert_awaited_once_with(
            AVTRANSPORT_URN,
            "Seek",
            {"InstanceID": 0, "Unit": "REL_TIME", "Target": "00:02:05"},
        )

    async def test_status_includes_real_renderer_position(self):
        client = self.make_client()
        async def soap(urn, action, arguments):
            if action == "GetPositionInfo":
                return {"RelTime": "00:01:02.5", "TrackDuration": "01:02:03"}
            if action == "GetCurrentTransportActions":
                return {"Actions": "Play, Pause, Seek"}
            return {"CurrentTransportState": "PLAYING"}
        client._soap = AsyncMock(side_effect=soap)
        client.get_volume = AsyncMock(return_value=16)
        self.assertEqual(await client.get_status(), {
            "status": 1, "volume": 16, "seek_supported": True,
            "position_seconds": 62.5, "duration_seconds": 3723,
        })

    async def test_unsupported_position_does_not_break_status(self):
        client = self.make_client()
        async def soap(urn, action, arguments):
            if action == "GetPositionInfo":
                raise aiohttp.ClientError("Unsupported action")
            return {"CurrentTransportState": "PLAYING"}
        client._soap = AsyncMock(side_effect=soap)
        client.get_volume = AsyncMock(return_value=16)
        self.assertEqual(await client.get_status(), {"status": 1, "volume": 16, "seek_supported": False})

    def test_transport_time_rejects_unknown_and_malformed_values(self):
        for value in ("", "NOT_IMPLEMENTED", "-1:00:00", "00:60:00", "NaN", "00:00:inf"):
            self.assertIsNone(_parse_transport_time(value))
        self.assertEqual(_parse_transport_time("100:00:00"), 360000)
        self.assertEqual(_parse_transport_time("00:00:00"), 0)

    async def test_soap_rediscovers_renderer_after_control_port_changes(self):
        client = LocalDLNAClient(
            "http://192.0.2.10:1269/",
            {
                AVTRANSPORT_URN: "http://192.0.2.10:1269/av/control.xml",
                RENDERING_CONTROL_URN: "http://192.0.2.10:1269/rc/control.xml",
            },
            device_id="uuid:device",
            interface_ip="192.0.2.20",
        )
        new_location = "http://192.0.2.10:2026/"
        new_services = {
            AVTRANSPORT_URN: "http://192.0.2.10:2026/av/control.xml",
            RENDERING_CONTROL_URN: "http://192.0.2.10:2026/rc/control.xml",
        }

        with (
            patch.object(
                client,
                "_soap_once",
                AsyncMock(
                    side_effect=[
                        aiohttp.ClientConnectionError("stale control port"),
                        {"CurrentVolume": "27"},
                    ]
                ),
            ) as soap_once,
            patch.object(
                client,
                "_discover_location",
                AsyncMock(return_value=new_location),
            ) as discover,
            patch.object(
                client,
                "_load_services",
                AsyncMock(return_value=new_services),
            ) as load_services,
        ):
            self.assertEqual(await client.get_volume(), 27)

        discover.assert_awaited_once_with("uuid:device", "192.0.2.20")
        load_services.assert_awaited_once_with(new_location)
        self.assertEqual(client.location, new_location)
        self.assertEqual(client.services, new_services)
        self.assertEqual(soap_once.await_count, 2)
        self.assertEqual(
            soap_once.await_args_list[0].args[0],
            "http://192.0.2.10:1269/rc/control.xml",
        )
        self.assertEqual(
            soap_once.await_args_list[1].args[0],
            "http://192.0.2.10:2026/rc/control.xml",
        )

    async def test_concurrent_commands_share_one_endpoint_rediscovery(self):
        client = LocalDLNAClient(
            "http://192.0.2.10:1269/",
            {
                AVTRANSPORT_URN: "http://192.0.2.10:1269/av/control.xml",
                RENDERING_CONTROL_URN: "http://192.0.2.10:1269/rc/control.xml",
            },
            device_id="uuid:device",
            interface_ip="192.0.2.20",
        )
        new_location = "http://192.0.2.10:2026/"
        new_services = {
            AVTRANSPORT_URN: "http://192.0.2.10:2026/av/control.xml",
            RENDERING_CONTROL_URN: "http://192.0.2.10:2026/rc/control.xml",
        }

        async def soap_once(service_url, urn, action, arguments):
            del urn, action, arguments
            if ":1269/" in service_url:
                raise aiohttp.ClientConnectionError("stale control port")
            return {"CurrentVolume": "31"}

        with (
            patch.object(client, "_soap_once", side_effect=soap_once),
            patch.object(
                client,
                "_discover_location",
                AsyncMock(return_value=new_location),
            ) as discover,
            patch.object(
                client,
                "_load_services",
                AsyncMock(return_value=new_services),
            ),
        ):
            first, second = await asyncio.gather(
                client.get_volume(),
                client.get_volume(),
            )

        self.assertEqual((first, second), (31, 31))
        discover.assert_awaited_once()

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
