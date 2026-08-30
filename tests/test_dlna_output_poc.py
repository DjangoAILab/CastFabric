"""Protocol-level POC for the MiPlay -> CastFabric -> physical DMR path."""

from __future__ import annotations

import asyncio
import struct
import xml.etree.ElementTree as ET

import aiohttp
from aiohttp import web

from miair.dlna.client import AVTRANSPORT_URN, LocalDLNAClient
from miair.outputs.dlna import DLNAOutputAdapter
from miair.streaming.sink import CastFabricLiveAudioSink


class FakePhysicalDMR:
    """A tiny UPnP renderer that accepts SOAP and then pulls the media URL."""

    def __init__(self, expected_body_size: int):
        self.expected_body_size = expected_body_size
        self.current_uri = ""
        self.audio = b""
        self.actions: list[str] = []
        self.pull_done = asyncio.Event()
        self._pull_task: asyncio.Task | None = None
        self._runner: web.AppRunner | None = None
        self.control_url = ""

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/upnp/control/avtransport", self._control)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.control_url = f"http://127.0.0.1:{port}/upnp/control/avtransport"

    async def stop(self) -> None:
        if self._pull_task is not None and not self._pull_task.done():
            self._pull_task.cancel()
            await asyncio.gather(self._pull_task, return_exceptions=True)
        if self._runner is not None:
            await self._runner.cleanup()

    async def _control(self, request: web.Request) -> web.Response:
        soap_action = request.headers.get("SOAPAction", "").strip('"')
        action = soap_action.rsplit("#", 1)[-1]
        self.actions.append(action)
        payload = await request.read()
        if action == "SetAVTransportURI":
            root = ET.fromstring(payload)
            self.current_uri = next(
                node.text or ""
                for node in root.iter()
                if node.tag.rsplit("}", 1)[-1] == "CurrentURI"
            )
        elif action == "Play":
            self._pull_task = asyncio.create_task(self._pull_audio())
        return web.Response(
            body=(
                '<?xml version="1.0"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                f'<s:Body><u:{action}Response xmlns:u="{AVTRANSPORT_URN}"/>'
                '</s:Body></s:Envelope>'
            ).encode(),
            content_type="text/xml",
        )

    async def _pull_audio(self) -> None:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.current_uri) as response:
                response.raise_for_status()
                self.audio = await response.content.readexactly(
                    44 + self.expected_body_size
                )
        self.pull_done.set()


def test_two_physical_dmr_targets_pull_independent_live_audio_streams():
    async def scenario():
        payload_a = struct.pack("<1920h", *([700] * 1920))
        payload_b = struct.pack("<1920h", *([-900] * 1920))
        dmr_a = FakePhysicalDMR(len(payload_a))
        dmr_b = FakePhysicalDMR(len(payload_b))
        await asyncio.gather(dmr_a.start(), dmr_b.start())

        def adapter(target_id: str, dmr: FakePhysicalDMR) -> DLNAOutputAdapter:
            client = LocalDLNAClient(
                dmr.control_url,
                {AVTRANSPORT_URN: dmr.control_url},
            )
            return DLNAOutputAdapter(target_id, target_id, client)

        lifecycle_a = []
        lifecycle_b = []
        sink_a = CastFabricLiveAudioSink(
            "127.0.0.1",
            adapter("speaker-a", dmr_a),
            lifecycle_callback=lambda event, details: lifecycle_a.append(event),
        )
        sink_b = CastFabricLiveAudioSink(
            "127.0.0.1",
            adapter("speaker-b", dmr_b),
            lifecycle_callback=lambda event, details: lifecycle_b.append(event),
        )
        try:
            await asyncio.gather(
                sink_a.start(48_000, 2, 2),
                sink_b.start(48_000, 2, 2),
            )
            await asyncio.gather(sink_a.write(payload_a), sink_b.write(payload_b))
            await asyncio.wait_for(
                asyncio.gather(dmr_a.pull_done.wait(), dmr_b.pull_done.wait()),
                timeout=3,
            )
            return (
                payload_a,
                payload_b,
                dmr_a,
                dmr_b,
                sink_a,
                sink_b,
                lifecycle_a,
                lifecycle_b,
            )
        finally:
            await asyncio.gather(sink_a.stop(), sink_b.stop())
            await asyncio.gather(dmr_a.stop(), dmr_b.stop())

    (
        payload_a,
        payload_b,
        dmr_a,
        dmr_b,
        sink_a,
        sink_b,
        lifecycle_a,
        lifecycle_b,
    ) = asyncio.run(scenario())

    assert dmr_a.current_uri != dmr_b.current_uri
    assert dmr_a.actions[:2] == ["SetAVTransportURI", "Play"]
    assert dmr_b.actions[:2] == ["SetAVTransportURI", "Play"]
    assert dmr_a.audio[:4] == dmr_b.audio[:4] == b"RIFF"
    assert dmr_a.audio[44:] == payload_a
    assert dmr_b.audio[44:] == payload_b
    assert dmr_a.audio[44:] != dmr_b.audio[44:]
    assert sink_a.diagnostics()["pcm_bytes"] == len(payload_a)
    assert sink_b.diagnostics()["pcm_bytes"] == len(payload_b)
    assert lifecycle_a == ["output_started", "pcm_forwarded", "output_stopped"]
    assert lifecycle_b == ["output_started", "pcm_forwarded", "output_stopped"]
