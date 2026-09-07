import asyncio
import math
import struct

from miair.miplay.media import RecordingPcmSink
from miair.miplay.receiver import MiPlayReceiver
from miair.miplay.simulator import MiPlaySourceSimulator


def test_loopback_source_reaches_receiver_pcm_sink():
    async def scenario():
        sink = RecordingPcmSink()
        volume_changed = asyncio.Event()
        volumes = []
        lifecycle = []

        async def set_volume(volume):
            volumes.append(volume)
            volume_changed.set()
            return True

        async def on_lifecycle(event, details):
            lifecycle.append((event, details))

        receiver = MiPlayReceiver(
            host="127.0.0.1",
            port=0,
            sink_factory=lambda: sink,
            advertise=False,
            volume_setter=set_volume,
            lifecycle_callback=on_lifecycle,
        )
        await receiver.start()
        try:
            simulator = MiPlaySourceSimulator(
                target_host="127.0.0.1",
                target_port=receiver.port,
                source_host="127.0.0.1",
                tone_frequency=440,
                duration=0.35,
                volume=43,
            )
            result = await asyncio.wait_for(simulator.run(), timeout=15)
            await asyncio.wait_for(volume_changed.wait(), timeout=2)
            await asyncio.wait_for(receiver.wait_for_idle(), timeout=5)
            return sink, receiver.diagnostics(), result, volumes, lifecycle
        finally:
            await receiver.stop()

    sink, diagnostics, result, volumes, lifecycle = asyncio.run(scenario())
    pcm = b"".join(sink.chunks)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)

    assert result.control_opened
    assert result.rtsp_ready
    assert result.media_frames > 0
    assert result.notifications == {"first-audiopcm": 1, "state": 2}
    assert diagnostics["last_session"]["authenticated"] is True
    assert diagnostics["last_session"]["rtsp_ready"] is True
    assert diagnostics["last_session"]["media_frames"] == result.media_frames
    assert diagnostics["last_session"]["peer"] == "<local-address>"
    assert "127.0.0.1" not in str(diagnostics)
    assert sink.sample_rate == 48_000
    assert sink.channels == 2
    assert len(pcm) > 48_000 * 2 * 2 // 5
    assert max(abs(value) for value in samples) > 500
    assert volumes == [43]
    assert [event for event, _ in lifecycle] == [
        "session_started",
        "media_started",
        "session_ended",
    ]
    assert lifecycle[0][1].get("source_app") is None


def test_idle_tcp_probe_does_not_claim_a_media_session():
    async def scenario():
        lifecycle = []

        async def on_lifecycle(event, details):
            lifecycle.append((event, details))

        receiver = MiPlayReceiver(
            host="127.0.0.1",
            port=0,
            sink_factory=RecordingPcmSink,
            advertise=False,
            lifecycle_callback=on_lifecycle,
            handshake_timeout=0.05,
        )
        await receiver.start()
        try:
            _reader, writer = await asyncio.open_connection(
                "127.0.0.1", receiver.port
            )
            for _ in range(20):
                if receiver.diagnostics()["control_connections"]:
                    break
                await asyncio.sleep(0.005)
            assert receiver.diagnostics()["control_connections"] == 1
            assert receiver.diagnostics()["active_session"] is False
            await asyncio.wait_for(receiver.wait_for_idle(), timeout=1)
            writer.close()
            await writer.wait_closed()
            return lifecycle, receiver.diagnostics()
        finally:
            await receiver.stop()

    lifecycle, diagnostics = asyncio.run(scenario())

    assert lifecycle == []
    assert diagnostics["active_session"] is False
    assert diagnostics["last_session"]["authenticated"] is False
    assert diagnostics["last_session"]["error"] == "TimeoutError"


def test_idle_tcp_probe_does_not_block_a_valid_miplay_sender():
    async def scenario():
        receiver = MiPlayReceiver(
            host="127.0.0.1",
            port=0,
            sink_factory=RecordingPcmSink,
            advertise=False,
            handshake_timeout=0.5,
        )
        await receiver.start()
        try:
            _reader, idle_writer = await asyncio.open_connection(
                "127.0.0.1", receiver.port
            )
            result = await MiPlaySourceSimulator(
                target_host="127.0.0.1",
                target_port=receiver.port,
                duration=0.1,
            ).run()
            idle_writer.close()
            await idle_writer.wait_closed()
            await asyncio.wait_for(receiver.wait_for_idle(), timeout=2)
            return result
        finally:
            await receiver.stop()

    result = asyncio.run(scenario())

    assert result.control_opened is True
    assert result.rtsp_ready is True
    assert result.media_frames > 0
