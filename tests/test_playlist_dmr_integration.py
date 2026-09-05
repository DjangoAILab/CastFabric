import asyncio
import xml.etree.ElementTree as ET

import aiohttp
import pytest
from aiohttp import web

from miair.content.media import MediaAssetService
from miair.content.playlists import PlaylistRunner, PlaylistService
from miair.content.repository import ContentRepository
from miair.dlna.client import AVTRANSPORT_URN, RENDERING_CONTROL_URN, LocalDLNAClient
from miair.outputs.dlna import DLNAOutputAdapter
from miair.playback.service import PlaybackService
from miair.runtime.sessions import MediaSessionCoordinator
from miair.runtime.suites import ReceiverSuiteRegistry
from miair.targets import OutputTargetConfig


class PullingDMR:
    def __init__(self, end_state):
        self.end_state = end_state
        self.current_uri = None
        self.actions = []
        self.pulls = []
        self._tasks = []
        self._runner = None

    async def start(self):
        app = web.Application()
        app.router.add_post("/avtransport", self.control)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}/avtransport"

    async def control(self, request):
        action = request.headers["SOAPAction"].strip('"').rsplit("#", 1)[-1]
        self.actions.append(action)
        if action == "SetAVTransportURI":
            root = ET.fromstring(await request.read())
            self.current_uri = next(
                node.text for node in root.iter()
                if node.tag.rsplit("}", 1)[-1] == "CurrentURI"
            )
        elif action == "Play":
            self._tasks.append(asyncio.create_task(self.pull(self.current_uri)))
        values = {}
        if action == "GetTransportInfo":
            values = {"CurrentTransportState": self.end_state}
        elif action == "GetPositionInfo":
            values = {"RelTime": "00:00:01", "TrackDuration": "00:00:01"}
        elif action == "GetVolume":
            values = {"CurrentVolume": "16"}
        fields = "".join(f"<{key}>{value}</{key}>" for key, value in values.items())
        return web.Response(
            text=(
                '<?xml version="1.0"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                f'<s:Body><u:{action}Response xmlns:u="{AVTRANSPORT_URN}">{fields}</u:{action}Response>'
                '</s:Body></s:Envelope>'
            ),
            content_type="text/xml",
        )

    async def pull(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                self.pulls.append((url, await response.read()))

    async def wait_for_pulls(self, count):
        for _ in range(100):
            if len(self.pulls) >= count:
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"renderer only pulled {len(self.pulls)} items")

    async def close(self):
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._runner:
            await self._runner.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("end_state", ["STOPPED", "PLAYING"])
async def test_server_playlist_advances_and_fake_dmr_pulls_each_item(tmp_path, end_state):
    async def first_media(_request):
        return web.Response(body=b"first-audio")

    async def second_media(_request):
        return web.Response(body=b"second-audio")

    media_app = web.Application()
    media_app.router.add_get("/one.mp3", first_media)
    media_app.router.add_get("/two.mp3", second_media)
    media_runner = web.AppRunner(media_app)
    await media_runner.setup()
    media_site = web.TCPSite(media_runner, "127.0.0.1", 0)
    await media_site.start()
    media_port = media_site._server.sockets[0].getsockname()[1]

    dmr = PullingDMR(end_state)
    control_url = await dmr.start()
    repository = ContentRepository(tmp_path / "castfabric.sqlite3")
    assets = MediaAssetService(
        repository, tmp_path / "media",
        id_factory=iter(["asset-one", "asset-two"]).__next__,
    )
    playlists = PlaylistService(
        repository,
        id_factory=iter(["playlist", "item-one", "item-two"]).__next__,
    )
    assets.create_external_url(
        f"http://127.0.0.1:{media_port}/one.mp3", display_name="One"
    )
    assets.create_external_url(
        f"http://127.0.0.1:{media_port}/two.mp3", display_name="Two"
    )
    playlists.create_playlist("Morning")
    playlists.add_item("playlist", "asset-one", expected_revision=1)
    playlists.add_item("playlist", "asset-two", expected_revision=2)

    adapter = DLNAOutputAdapter(
        "uuid:physical", "Physical",
        LocalDLNAClient(control_url, {
            AVTRANSPORT_URN: control_url, RENDERING_CONTROL_URN: control_url,
        }),
    )
    target = OutputTargetConfig(
        id="uuid:physical", name="Physical", virtual_udn="physical-virtual"
    )
    registry = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    registry.register(target, "physical-controller", adapter)
    playback = PlaybackService(registry, MediaSessionCoordinator(repository=repository))
    runner = PlaylistRunner(
        repository, playlists, assets, playback,
        media_origin="http://127.0.0.1:8300", poll_interval=0.25,
        id_factory=iter(["run", "session-one", "session-two"]).__next__,
    )
    try:
        started = await runner.start_playlist("playlist", "uuid:physical")
        await dmr.wait_for_pulls(1)
        await dmr.wait_for_pulls(2)
        for _ in range(100):
            ended = runner.get_run(started["run_id"])
            if ended["state"] == "ended":
                break
            await asyncio.sleep(0.01)

        assert [body for _url, body in dmr.pulls] == [b"first-audio", b"second-audio"]
        assert [action for action in dmr.actions if action in {"SetAVTransportURI", "Play"}] == [
            "SetAVTransportURI", "Play", "SetAVTransportURI", "Play"
        ]
        assert ended["end_reason"] == "completed"
        assert repository.active_session("uuid:physical") is None
    finally:
        await runner.close()
        repository.close()
        await dmr.close()
        await media_runner.cleanup()
