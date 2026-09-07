from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from miair.playback.streams import PcmStreamError, PcmStreamRegistry
from miair.runtime.models import IngressProtocol, SessionState
from miair.runtime.sessions import MediaSessionCoordinator
from miair.runtime.suites import ReceiverSuiteRegistry
from miair.targets import OutputTargetConfig


class FakeSink:
    def __init__(self):
        self.start = AsyncMock()
        self.write = AsyncMock()
        self.stop = AsyncMock()
        self.lifecycle_callback = None
        self.output_owner = None


def _registry(*, lifecycle_callback=None):
    controller = SimpleNamespace()
    target = OutputTargetConfig(id="uuid:living", name="Living")
    suites = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    suite = suites.register(target, "controller", controller)
    sessions = MediaSessionCoordinator(id_factory=lambda: "session-stream")
    playback = SimpleNamespace(
        suite_registry=suites,
        session_coordinator=sessions,
        controller_for=lambda _target_id: controller,
    )
    sinks = []

    def make_sink(_hostname, _controller):
        sink = FakeSink()
        sinks.append(sink)
        return sink

    registry = PcmStreamRegistry(
        playback,
        hostname="127.0.0.1",
        sink_factory=make_sink,
        lifecycle_callback=lifecycle_callback,
        id_factory=lambda: "stream-token",
    )
    return registry, suite, sessions, sinks


@pytest.mark.asyncio
async def test_fixed_pcm_stream_starts_sink_and_mcp_session():
    registry, suite, sessions, sinks = _registry()

    result = await registry.create(
        "uuid:living", sample_format="s16le", sample_rate=48000, channels=2
    )

    sinks[0].start.assert_awaited_once_with(48000, 2, 2)
    current = sessions.current("uuid:living")
    assert current.protocol is IngressProtocol.MCP
    assert current.state is SessionState.PLAYING
    assert suite.current_session_id == "session-stream"
    assert result["stream_id"] == "stream-token"
    assert result["stream_path"].endswith("/stream-token")
    assert result["format"] == {
        "sample_format": "s16le",
        "sample_rate": 48000,
        "channels": 2,
    }
    assert sinks[0].output_owner() is True


@pytest.mark.asyncio
async def test_pcm_sink_lifecycle_is_attributed_to_normalized_target():
    lifecycle = AsyncMock()
    registry, _suite, _sessions, sinks = _registry(
        lifecycle_callback=lifecycle
    )

    await registry.create(
        " UUID:LIVING ", sample_format="s16le", sample_rate=48000, channels=2
    )
    await sinks[0].lifecycle_callback("output_started", {"media_format": "wav"})

    lifecycle.assert_awaited_once_with(
        "uuid:living", "output_started", {"media_format": "wav"}
    )


@pytest.mark.asyncio
async def test_stream_has_one_writer_and_binary_bytes_are_forwarded_unchanged():
    registry, _suite, sessions, sinks = _registry()
    await registry.create(
        "uuid:living", sample_format="s16le", sample_rate=48000, channels=2
    )

    stream = registry.claim_writer("stream-token")
    with pytest.raises(PcmStreamError) as second:
        registry.claim_writer("stream-token")
    assert second.value.code == "STREAM_ALREADY_CONNECTED"

    await registry.write(stream, b"\x01\x02\x03\x04")
    await registry.close("stream-token")

    sinks[0].write.assert_awaited_once_with(b"\x01\x02\x03\x04")
    sinks[0].stop.assert_awaited_once_with()
    assert sessions.current("uuid:living") is None


@pytest.mark.asyncio
async def test_invalid_format_and_unknown_stream_have_stable_errors():
    registry, _suite, _sessions, _sinks = _registry()
    for values in [
        ("f32le", 48000, 2),
        ("s16le", 44100, 2),
        ("s16le", 48000, 1),
    ]:
        with pytest.raises(PcmStreamError) as error:
            await registry.create(
                "uuid:living",
                sample_format=values[0],
                sample_rate=values[1],
                channels=values[2],
            )
        assert error.value.code == "UNSUPPORTED_PCM_FORMAT"

    with pytest.raises(PcmStreamError) as missing:
        registry.claim_writer("unknown")
    assert missing.value.code == "STREAM_NOT_FOUND"


@pytest.mark.asyncio
async def test_external_stop_closes_pcm_server_without_stopping_output_twice():
    registry, _suite, sessions, sinks = _registry()
    await registry.create(
        "uuid:living", sample_format="s16le", sample_rate=48000, channels=2
    )

    await registry.stop_target("uuid:living", stop_output=False)

    sinks[0].stop.assert_awaited_once_with(stop_output=False)
    assert sessions.current("uuid:living") is None
