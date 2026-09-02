from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from miair.playback.service import PlaybackService, PlaybackServiceError
from miair.runtime.models import IngressProtocol, SessionState
from miair.runtime.sessions import MediaSessionCoordinator
from miair.runtime.suites import ReceiverSuiteRegistry
from miair.targets import OutputTargetConfig


def _service(*, enabled=True, accepted=True):
    target = OutputTargetConfig(
        id="UUID:Living",
        name="Living",
        enabled=enabled,
        virtual_udn="living-virtual",
    )
    controller = SimpleNamespace(
        play_url=AsyncMock(return_value=accepted),
        pause=AsyncMock(return_value=accepted),
        stop=AsyncMock(return_value=accepted),
        set_volume=AsyncMock(return_value=accepted),
        seek=AsyncMock(return_value=accepted),
        get_status=AsyncMock(return_value={"status": 1, "volume": 23}),
    )
    suites = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    suite = suites.register(target, "living-controller", controller)
    sessions = MediaSessionCoordinator(id_factory=lambda: "session-mcp")
    return PlaybackService(suites, sessions), suite, controller, sessions


def test_controller_lookup_normalizes_target_id_and_rejects_invalid_targets():
    service, _suite, controller, _sessions = _service()

    assert service.controller_for("uuid:living") is controller

    with pytest.raises(PlaybackServiceError) as missing:
        service.controller_for("uuid:missing")
    assert missing.value.code == "TARGET_NOT_FOUND"

    disabled, _suite, _controller, _sessions = _service(enabled=False)
    with pytest.raises(PlaybackServiceError) as error:
        disabled.controller_for("uuid:living")
    assert error.value.code == "TARGET_DISABLED"


@pytest.mark.asyncio
async def test_url_playback_owns_an_mcp_session_and_delegates_once():
    service, suite, controller, sessions = _service()

    result = await service.play_url(
        "uuid:living", "https://example.test/audio.mp3", media_format="audio/mpeg"
    )

    controller.play_url.assert_awaited_once_with(
        "https://example.test/audio.mp3", play_type=2
    )
    current = sessions.current("uuid:living")
    assert current.id == "session-mcp"
    assert current.protocol is IngressProtocol.MCP
    assert current.state is SessionState.PLAYING
    assert suite.current_session_id == current.id
    assert result == {
        "ok": True,
        "target_id": "uuid:living",
        "session_id": "session-mcp",
        "state": "playing",
    }
    controller.seek.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_url_command_ends_the_new_session_as_failed():
    service, suite, _controller, sessions = _service(accepted=False)

    with pytest.raises(PlaybackServiceError) as error:
        await service.play_url("uuid:living", "https://example.test/audio.mp3")

    assert error.value.code == "TARGET_COMMAND_FAILED"
    assert sessions.current("uuid:living") is None
    assert sessions.query(include_recent=True)[0].state is SessionState.FAILED
    assert suite.current_session_id is None


@pytest.mark.asyncio
async def test_controls_delegate_and_only_stop_the_current_mcp_session():
    service, suite, controller, sessions = _service()
    await service.play_url("uuid:living", "https://example.test/audio.mp3")

    paused = await service.pause("uuid:living")
    volume = await service.set_volume("uuid:living", 130)
    status = await service.get_status("uuid:living")
    stopped = await service.stop("uuid:living")

    controller.pause.assert_awaited_once_with()
    controller.set_volume.assert_awaited_once_with(100)
    controller.get_status.assert_awaited_once_with()
    controller.stop.assert_awaited_once_with()
    assert paused["state"] == "paused"
    assert volume["volume"] == 100
    assert status == {
        "ok": True,
        "target_id": "uuid:living",
        "state": "playing",
        "volume": 23,
    }
    assert stopped["state"] == "stopped"
    assert sessions.current("uuid:living") is None
    assert suite.current_session_id is None


@pytest.mark.asyncio
async def test_play_at_and_current_seek_share_controller_primitive():
    service, _suite, controller, sessions = _service()

    played = await service.play_url(
        "uuid:living", "https://example.test/audio.mp3", start_position_seconds=90
    )
    seeked = await service.seek(
        "uuid:living", 125, if_session_id=played["session_id"]
    )

    controller.play_url.assert_awaited_once()
    assert controller.seek.await_args_list[0].args == (90,)
    assert controller.seek.await_args_list[1].args == (125,)
    assert seeked["session_id"] == sessions.current("uuid:living").id


@pytest.mark.asyncio
async def test_seek_can_control_untracked_current_playback_without_claiming_state():
    service, _suite, controller, _sessions = _service()

    result = await service.seek("uuid:living", 15)

    controller.seek.assert_awaited_once_with(15)
    assert result["session_id"] is None
    assert result["state"] == "unknown"


@pytest.mark.asyncio
async def test_seek_rejects_invalid_position_and_changed_session():
    service, _suite, controller, _sessions = _service()
    played = await service.play_url("uuid:living", "https://example.test/audio.mp3")

    with pytest.raises(PlaybackServiceError) as invalid:
        await service.seek("uuid:living", -1)
    assert invalid.value.code == "INVALID_POSITION"
    with pytest.raises(PlaybackServiceError) as changed:
        await service.seek("uuid:living", 10, if_session_id=played["session_id"] + "-old")
    assert changed.value.code == "SESSION_CHANGED"
    controller.seek.assert_not_awaited()


@pytest.mark.asyncio
async def test_play_at_stops_started_output_when_initial_seek_is_unsupported():
    service, suite, controller, sessions = _service()
    controller.seek.return_value = False

    with pytest.raises(PlaybackServiceError) as error:
        await service.play_url(
            "uuid:living",
            "https://example.test/audio.mp3",
            start_position_seconds=30,
        )

    assert error.value.code == "SEEK_UNSUPPORTED"
    controller.stop.assert_awaited_once_with()
    assert sessions.current("uuid:living") is None
    assert sessions.query(include_recent=True)[0].state is SessionState.FAILED
    assert suite.current_session_id is None


@pytest.mark.asyncio
async def test_stop_does_not_end_a_session_owned_by_another_ingress():
    service, suite, _controller, sessions = _service()
    airplay = await sessions.begin("uuid:living", IngressProtocol.AIRPLAY)
    suite.current_session_id = airplay.id

    await service.stop("uuid:living")

    assert sessions.current("uuid:living").id == airplay.id
    assert suite.current_session_id == airplay.id
