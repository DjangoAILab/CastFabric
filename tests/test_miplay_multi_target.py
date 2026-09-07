from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from miair.app import CastFabric
from miair.config import Config
from miair.runtime.models import IngressProtocol, IngressState
from miair.runtime.models import SessionState
from miair.targets import OutputTargetConfig


class FakeSpeaker:
    def __init__(self, name: str):
        self.name = name

    def get_dlna_name(self):
        return self.name


def _app(tmp_path, *, base_port=18899):
    targets = {
        "uuid:bedroom": OutputTargetConfig(
            id="uuid:bedroom", name="Bedroom", virtual_udn="bedroom-virtual"
        ),
        "uuid:living": OutputTargetConfig(
            id="uuid:living", name="Living", virtual_udn="living-virtual"
        ),
    }
    app = CastFabric(
        Config(
            hostname="192.168.133.5",
            conf_path=str(tmp_path),
            enable_miplay=True,
            miplay_port=base_port,
            targets=targets,
        )
    )
    controllers = {}
    for target_id in ("uuid:living", "uuid:bedroom"):
        controller = SimpleNamespace(
            target_id=target_id,
            speaker=FakeSpeaker(targets[target_id].name),
            set_volume=AsyncMock(return_value=True),
            play_url=AsyncMock(return_value=True),
            stop=AsyncMock(return_value=True),
        )
        controllers[target_id] = controller
        app.speaker_manager.controllers[target_id] = controller
        app.suite_registry.register(targets[target_id], target_id, controller)
    return app, controllers


@pytest.mark.asyncio
async def test_two_targets_get_stable_unique_ports_identities_and_controller_bindings(tmp_path):
    app, controllers = _app(tmp_path, base_port=18899)
    created = []

    def receiver_factory(**kwargs):
        receiver = SimpleNamespace(
            port=kwargs["port"],
            identity=kwargs["identity"],
            start=AsyncMock(),
            stop=AsyncMock(),
        )
        created.append((receiver, kwargs))
        return receiver

    with patch("miair.app.MiPlayReceiver", side_effect=receiver_factory):
        await app._start_miplay_for_speakers()

    assert set(app.miplay_receivers) == {"uuid:bedroom", "uuid:living"}
    assert [kwargs["port"] for _, kwargs in created] == [18899, 18900]
    assert len({kwargs["identity"].device_id for _, kwargs in created}) == 2
    assert len({kwargs["identity"].instance for _, kwargs in created}) == 2
    assert [kwargs["identity"].friendly_name for _, kwargs in created] == [
        "CastFabric · Bedroom",
        "CastFabric · Living",
    ]
    assert [kwargs["sink_factory"]().controller for _, kwargs in created] == [
        controllers["uuid:bedroom"],
        controllers["uuid:living"],
    ]
    assert app.miplay_receiver is app.miplay_receivers["uuid:bedroom"]


@pytest.mark.asyncio
async def test_one_port_collision_degrades_only_that_targets_miplay(tmp_path):
    app, _ = _app(tmp_path)
    starts = [AsyncMock(), AsyncMock(side_effect=OSError("address in use"))]
    stopped = [AsyncMock(), AsyncMock()]
    index = 0

    def receiver_factory(**kwargs):
        nonlocal index
        receiver = SimpleNamespace(
            port=kwargs["port"],
            start=starts[index],
            stop=stopped[index],
        )
        index += 1
        return receiver

    with patch("miair.app.MiPlayReceiver", side_effect=receiver_factory):
        await app._start_miplay_for_speakers()

    assert set(app.miplay_receivers) == {"uuid:bedroom"}
    bedroom = app.suite_registry.get("uuid:bedroom").get_ingress(IngressProtocol.MIPLAY)
    living = app.suite_registry.get("uuid:living").get_ingress(IngressProtocol.MIPLAY)
    assert bedroom.state is IngressState.READY
    assert living.state is IngressState.UNAVAILABLE
    assert living.error_code == "MIPLAY_PORT_BIND_FAILED"
    stopped[1].assert_awaited_once()


@pytest.mark.asyncio
async def test_port_overflow_does_not_prevent_valid_target_from_starting(tmp_path):
    app, _ = _app(tmp_path, base_port=65535)
    receiver = SimpleNamespace(port=65535, start=AsyncMock(), stop=AsyncMock())

    with patch("miair.app.MiPlayReceiver", return_value=receiver) as receiver_type:
        await app._start_miplay_for_speakers()

    receiver_type.assert_called_once()
    assert set(app.miplay_receivers) == {"uuid:bedroom"}
    overflow = app.suite_registry.get("uuid:living").get_ingress(IngressProtocol.MIPLAY)
    assert overflow.state is IngressState.UNAVAILABLE
    assert overflow.error_code == "MIPLAY_PORT_OUT_OF_RANGE"


@pytest.mark.asyncio
async def test_stop_cleans_every_miplay_receiver(tmp_path):
    app, _ = _app(tmp_path)
    first = SimpleNamespace(stop=AsyncMock(side_effect=RuntimeError("injected stop failure")))
    second = SimpleNamespace(stop=AsyncMock())
    app.miplay_receivers = {
        "uuid:bedroom": first,
        "uuid:living": second,
    }

    await app._stop_dlna_services()

    first.stop.assert_awaited_once()
    second.stop.assert_awaited_once()
    assert app.miplay_receivers == {}
    assert app.miplay_receiver is None


@pytest.mark.asyncio
async def test_explicit_runtime_shutdown_stops_outputs_and_ends_sessions(tmp_path):
    app, controllers = _app(tmp_path)
    await app.playback_service.play_url(
        "uuid:living", "https://example.test/track.mp3"
    )

    await app._stop_dlna_services(stop_outputs=True)

    controllers["uuid:living"].stop.assert_awaited_once_with()
    assert app.session_coordinator.current("uuid:living") is None
    assert app.suite_registry.values() == ()


@pytest.mark.asyncio
async def test_lifecycle_records_verified_states_without_guessing_source_app(tmp_path):
    app, _ = _app(tmp_path)
    target_id = "uuid:living"
    app.suite_registry.set_ingress(
        target_id,
        IngressProtocol.MIPLAY,
        IngressState.READY,
        handle=object(),
        port=18900,
    )

    await app._handle_miplay_lifecycle(
        target_id,
        "session_started",
        {
            "client_address": "192.168.133.225",
            "media_format": "mpegts",
            "source_app": "must-not-be-used",
        },
    )
    session = app.session_coordinator.current(target_id)
    assert session is not None
    assert session.source.device_name is None
    assert session.source.provenance is None
    assert session.state is SessionState.STARTING

    await app._handle_miplay_output_lifecycle(
        target_id,
        "pcm_forwarded",
        {
            "media_format": "wav",
            "stream_url": "http://192.168.133.5:4567/miplay?token=secret",
            "source_app": "must-not-be-persisted",
        },
    )
    await app._handle_miplay_lifecycle(
        target_id,
        "media_started",
        {"media_format": "pcm_s16le"},
    )
    assert app.session_coordinator.current(target_id).state is SessionState.PLAYING
    event = app.activity_journal.query(target_id=target_id)[0]
    assert "source_app" not in event.details
    assert "token" not in event.details["stream_url"]
    assert "192.168.133.5" not in event.details["stream_url"]

    await app._handle_miplay_lifecycle(
        target_id,
        "session_ended",
        {"failed": False},
    )
    assert app.session_coordinator.current(target_id) is None
    assert app.suite_registry.get(target_id).current_session_id is None


@pytest.mark.asyncio
async def test_stale_miplay_end_cannot_clear_a_newer_mcp_session(tmp_path):
    app, _ = _app(tmp_path)
    target_id = "uuid:living"
    app.suite_registry.set_ingress(
        target_id,
        IngressProtocol.MIPLAY,
        IngressState.READY,
        handle=object(),
        port=18900,
    )

    await app._handle_miplay_lifecycle(
        target_id,
        "session_started",
        {"media_format": "mpegts"},
    )
    stale_id = app._miplay_session_ids[target_id]
    await app.playback_service.play_url(
        target_id, "https://example.test/new.mp3", media_format="audio/mpeg"
    )
    current = app.session_coordinator.current(target_id)
    assert (
        app.suite_registry.get(target_id).get_ingress(IngressProtocol.MIPLAY).state
        is IngressState.READY
    )

    await app._handle_miplay_output_lifecycle(
        target_id,
        "output_stopped",
        {},
    )
    await app._handle_miplay_lifecycle(
        target_id,
        "session_ended",
        {"failed": False},
    )

    assert app.session_coordinator.current(target_id).id == current.id
    assert app.suite_registry.get(target_id).current_session_id == current.id
    assert target_id not in app._miplay_session_ids
    output_event = app.activity_journal.query(target_id=target_id)[0]
    assert output_event.type == "miplay.output_stopped"
    assert output_event.session_id == stale_id
