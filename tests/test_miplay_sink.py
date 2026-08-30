import asyncio
import struct

import aiohttp

from miair.miplay.receiver import MiPlayReceiver
from miair.miplay.simulator import MiPlaySourceSimulator
from miair.streaming.sink import MiAirLiveAudioSink


class FakeSpeakerController:
    def __init__(self, request_headers=None, read_size=44 + 3840):
        self.url = None
        self.audio = b""
        self.fetch_task = None
        self.stop_calls = 0
        self.response_headers = None
        self.response_status = None
        self.request_headers = request_headers
        self.read_size = read_size
        self.play_type = None

    async def play_url(self, url, *, play_type=2):
        self.url = url
        self.play_type = play_type
        self.fetch_task = asyncio.create_task(self._fetch(url))
        return True

    async def _fetch(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.request_headers) as response:
                self.response_status = response.status
                self.response_headers = response.headers
                self.audio = await response.content.readexactly(self.read_size)

    async def stop(self):
        self.stop_calls += 1
        return True


def test_live_audio_sink_exposes_miplay_wav_and_controls_speaker():
    async def scenario():
        controller = FakeSpeakerController()
        lifecycle = []

        async def on_lifecycle(event, details):
            lifecycle.append((event, details))

        sink = MiAirLiveAudioSink(
            "127.0.0.1",
            controller,
            play_type=1,
            lifecycle_callback=on_lifecycle,
        )
        await sink.start(48_000, 2, 2)
        assert "/miplay/stream.wav" in controller.url
        await sink.write(struct.pack("<1920h", *([1000] * 1920)))
        await asyncio.wait_for(controller.fetch_task, timeout=3)
        await sink.stop()
        return controller, sink, lifecycle

    controller, sink, lifecycle = asyncio.run(scenario())

    assert controller.audio[:4] == b"RIFF"
    assert controller.audio[8:12] == b"WAVE"
    assert controller.audio[44:] == struct.pack("<1920h", *([1000] * 1920))
    assert "Transfer-Encoding" not in controller.response_headers
    assert controller.response_headers["transferMode.dlna.org"] == "Streaming"
    assert controller.response_headers["contentFeatures.dlna.org"] == (
        "DLNA.ORG_OP=00;DLNA.ORG_CI=0"
    )
    assert controller.stop_calls == 1
    assert controller.play_type == 1
    assert sink.diagnostics()["active"] is False
    assert [event for event, _ in lifecycle] == [
        "output_started",
        "pcm_forwarded",
        "output_stopped",
    ]


def test_live_audio_sink_can_advertise_finite_http_content_length():
    async def scenario():
        controller = FakeSpeakerController()
        sink = MiAirLiveAudioSink(
            "127.0.0.1", controller, http_mode="content-length"
        )
        await sink.start(48_000, 2, 2)
        await sink.write(struct.pack("<1920h", *([1000] * 1920)))
        await asyncio.wait_for(controller.fetch_task, timeout=3)
        await sink.stop()
        return controller

    controller = asyncio.run(scenario())

    assert controller.response_headers["Content-Length"] == str(
        44 + 0x7FFFFF00
    )
    assert "Transfer-Encoding" not in controller.response_headers


def test_live_audio_sink_supports_initial_open_byte_range():
    async def scenario():
        controller = FakeSpeakerController({"Range": "bytes=0-"})
        sink = MiAirLiveAudioSink("127.0.0.1", controller, http_mode="range")
        await sink.start(48_000, 2, 2)
        await sink.write(struct.pack("<1920h", *([1000] * 1920)))
        await asyncio.wait_for(controller.fetch_task, timeout=3)
        await sink.stop()
        return controller

    controller = asyncio.run(scenario())

    virtual_length = 44 + 0x7FFFFF00
    assert controller.response_status == 206
    assert controller.response_headers["Accept-Ranges"] == "bytes"
    assert controller.response_headers["Content-Range"] == (
        f"bytes 0-{virtual_length - 1}/{virtual_length}"
    )
    assert controller.response_headers["Content-Length"] == str(virtual_length)
    assert controller.response_headers["contentFeatures.dlna.org"] == (
        "DLNA.ORG_OP=01;DLNA.ORG_CI=0"
    )


def test_live_audio_sink_can_use_x_wav_content_type_without_changing_body():
    async def scenario():
        controller = FakeSpeakerController()
        sink = MiAirLiveAudioSink(
            "127.0.0.1", controller, content_type="audio/x-wav"
        )
        await sink.start(48_000, 2, 2)
        await sink.write(struct.pack("<1920h", *([1000] * 1920)))
        await asyncio.wait_for(controller.fetch_task, timeout=3)
        await sink.stop()
        return controller

    controller = asyncio.run(scenario())

    assert controller.response_headers["Content-Type"] == "audio/x-wav"
    assert controller.audio[:4] == b"RIFF"
    assert controller.audio[8:12] == b"WAVE"


def test_live_audio_sink_can_stream_standard_network_order_l16():
    async def scenario():
        controller = FakeSpeakerController(
            {"Range": "bytes=0-"}, read_size=3840
        )
        sink = MiAirLiveAudioSink(
            "127.0.0.1", controller, audio_format="l16", http_mode="range"
        )
        await sink.start(48_000, 2, 2)
        await sink.write(struct.pack("<1920h", *([1000] * 1920)))
        await asyncio.wait_for(controller.fetch_task, timeout=3)
        await sink.stop()
        return controller

    controller = asyncio.run(scenario())

    assert controller.url and "/miplay/stream.l16" in controller.url
    assert controller.response_status == 206
    assert controller.response_headers["Content-Type"] == (
        "audio/L16;rate=48000;channels=2"
    )
    assert controller.response_headers["Content-Length"] == str(0x7FFFFF00)
    assert controller.audio == struct.pack(">1920h", *([1000] * 1920))


def test_live_audio_sink_cleans_up_when_speaker_rejects_url():
    class RejectingController:
        async def play_url(self, url, *, play_type=2):
            return False

        async def stop(self):
            raise AssertionError("stop must not be called when play never started")

    async def scenario():
        sink = MiAirLiveAudioSink("127.0.0.1", RejectingController())
        try:
            await sink.start(48_000, 2, 2)
        except RuntimeError as exc:
            assert "rejected" in str(exc)
        else:
            raise AssertionError("expected rejected live URL")
        assert sink.diagnostics()["active"] is False

    asyncio.run(scenario())


def test_complete_miplay_wire_reaches_live_http_stream():
    class PullingController:
        def __init__(self):
            self.url = None
            self.audio = b""
            self.fetch_task = None

        async def play_url(self, url, *, play_type=2):
            self.url = url
            self.fetch_task = asyncio.create_task(self._fetch(url))
            return True

        async def _fetch(self, url):
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    self.audio = await response.read()

        async def stop(self):
            if self.fetch_task:
                await self.fetch_task
            return True

    async def scenario():
        controller = PullingController()
        receiver = MiPlayReceiver(
            host="127.0.0.1",
            port=0,
            sink_factory=lambda: MiAirLiveAudioSink("127.0.0.1", controller),
            advertise=False,
        )
        await receiver.start()
        try:
            result = await MiPlaySourceSimulator(
                target_host="127.0.0.1",
                target_port=receiver.port,
                duration=0.35,
            ).run()
            await asyncio.wait_for(receiver.wait_for_idle(), timeout=5)
            return controller, result, receiver.diagnostics()
        finally:
            await receiver.stop()

    controller, result, diagnostics = asyncio.run(scenario())

    assert result.rtsp_ready
    assert diagnostics["last_session"]["error"] is None
    assert controller.url and "/miplay/stream.wav" in controller.url
    assert controller.audio[:4] == b"RIFF"
    assert controller.audio[8:12] == b"WAVE"
    # The production sink intentionally retains at most ~160 ms of PCM.  The
    # simulator writes faster than real time, so asserting 200 ms made this
    # test scheduler-dependent after the low-latency queue was introduced.
    assert len(controller.audio) > 44 + 48_000 * 2 * 2 // 10
