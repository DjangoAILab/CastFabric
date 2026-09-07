import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from miair.app import MiAir
from miair.config import Config
from miair.targets import OutputTargetConfig


class FakeSpeaker:
    def get_dlna_name(self):
        return "书房 M01"


def test_app_starts_miplay_for_configured_suite():
    async def scenario():
        target = OutputTargetConfig(
            id="uuid:study",
            name="书房 M01",
            virtual_udn="study-virtual",
        )
        config = Config(
            hostname="192.168.31.9",
            enable_miplay=True,
            miplay_port=18899,
            miplay_name="OpenXiaoCast Test",
            miplay_play_type=1,
            miplay_http_mode="content-length",
            miplay_content_type="audio/x-wav",
            miplay_stream_format="l16",
            targets={target.id: target},
        )
        app = MiAir(config)
        controller = SimpleNamespace(
            target_id=target.id,
            speaker=FakeSpeaker(),
            set_volume=AsyncMock(return_value=True),
        )
        app.speaker_manager.controllers = {target.id: controller}
        app.suite_registry.register(target, target.id, controller)

        with patch("miair.app.MiPlayReceiver") as receiver_type:
            receiver = receiver_type.return_value
            receiver.start = AsyncMock()
            receiver.port = 18899
            await app._start_miplay_for_speaker()

            receiver_type.assert_called_once()
            kwargs = receiver_type.call_args.kwargs
            assert kwargs["port"] == 18899
            assert kwargs["advertise_address"] == "192.168.31.9"
            assert kwargs["identity"].friendly_name == "OpenXiaoCast Test · 书房 M01"
            sink = kwargs["sink_factory"]()
            assert sink.controller is controller
            assert sink.play_type == 1
            assert sink.http_mode == "content-length"
            assert sink.content_type == "audio/x-wav"
            assert sink.audio_format == "l16"
            assert await kwargs["volume_setter"](42) is False
            controller.set_volume.assert_not_awaited()
            await app._handle_miplay_lifecycle(
                target.id, "session_started", {"media_format": "mpegts"}
            )
            assert await kwargs["volume_setter"](42) is True
            controller.set_volume.assert_awaited_once_with(42)
            receiver.start.assert_awaited_once()

    asyncio.run(scenario())


def test_stopping_dlna_services_stops_miplay_before_clearing_state():
    async def scenario():
        app = MiAir(Config(hostname="127.0.0.1"))
        receiver = SimpleNamespace(stop=AsyncMock())
        app.miplay_receivers = {"uuid:study": receiver}
        await app._stop_dlna_services()
        receiver.stop.assert_awaited_once()
        assert app.miplay_receiver is None

    asyncio.run(scenario())


def test_miplay_config_bounds_port_and_name():
    config = Config(
        hostname="127.0.0.1",
        miplay_port=100_000,
        miplay_name="  " + "X" * 100,
        miplay_play_type=99,
        miplay_http_mode="range",
    )
    assert config.miplay_port == 65535
    assert config.miplay_name == "X" * 80
    assert config.miplay_play_type == 2
    assert config.miplay_http_mode == "range"

    invalid = Config(hostname="127.0.0.1", miplay_http_mode="invalid")
    assert invalid.miplay_http_mode == "close"

    invalid_mime = Config(
        hostname="127.0.0.1", miplay_content_type="application/octet-stream"
    )
    assert invalid_mime.miplay_content_type == "audio/wav"

    invalid_format = Config(
        hostname="127.0.0.1", miplay_stream_format="flac"
    )
    assert invalid_format.miplay_stream_format == "wav"
