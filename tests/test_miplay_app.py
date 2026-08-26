import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from miair.app import MiAir
from miair.config import Config


class FakeSpeaker:
    def get_dlna_name(self):
        return "书房 M01"


def test_app_starts_miplay_for_first_configured_speaker():
    async def scenario():
        config = Config(
            hostname="192.168.31.9",
            enable_miplay=True,
            miplay_port=18899,
            miplay_name="OpenXiaoCast Test",
            miplay_play_type=1,
        )
        app = MiAir(config)
        controller = SimpleNamespace(
            speaker=FakeSpeaker(),
            set_volume=AsyncMock(return_value=True),
        )
        app.speaker_manager.controllers = {"speaker-did": controller}

        with patch("miair.app.MiPlayReceiver") as receiver_type:
            receiver = receiver_type.return_value
            receiver.start = AsyncMock()
            await app._start_miplay_for_speaker()

            receiver_type.assert_called_once()
            kwargs = receiver_type.call_args.kwargs
            assert kwargs["port"] == 18899
            assert kwargs["advertise_address"] == "192.168.31.9"
            assert kwargs["identity"].friendly_name == "OpenXiaoCast Test · 书房 M01"
            sink = kwargs["sink_factory"]()
            assert sink.controller is controller
            assert sink.play_type == 1
            assert kwargs["volume_setter"] is controller.set_volume
            receiver.start.assert_awaited_once()

    asyncio.run(scenario())


def test_stopping_dlna_services_stops_miplay_before_clearing_state():
    async def scenario():
        app = MiAir(Config(hostname="127.0.0.1"))
        receiver = SimpleNamespace(stop=AsyncMock())
        app.miplay_receiver = receiver
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
    )
    assert config.miplay_port == 65535
    assert config.miplay_name == "X" * 80
    assert config.miplay_play_type == 2
