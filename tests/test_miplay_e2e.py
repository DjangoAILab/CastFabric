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

        async def set_volume(volume):
            volumes.append(volume)
            volume_changed.set()
            return True

        receiver = MiPlayReceiver(
            host="127.0.0.1",
            port=0,
            sink_factory=lambda: sink,
            advertise=False,
            volume_setter=set_volume,
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
            return sink, receiver.diagnostics(), result, volumes
        finally:
            await receiver.stop()

    sink, diagnostics, result, volumes = asyncio.run(scenario())
    pcm = b"".join(sink.chunks)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)

    assert result.control_opened
    assert result.rtsp_ready
    assert result.media_frames > 0
    assert result.notifications == {"first-audiopcm": 1, "state": 2}
    assert diagnostics["last_session"]["authenticated"] is True
    assert diagnostics["last_session"]["rtsp_ready"] is True
    assert diagnostics["last_session"]["media_frames"] == result.media_frames
    assert sink.sample_rate == 48_000
    assert sink.channels == 2
    assert len(pcm) > 48_000 * 2 * 2 // 5
    assert max(abs(value) for value in samples) > 500
    assert volumes == [43]
