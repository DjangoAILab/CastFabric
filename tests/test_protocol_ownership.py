from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from miair.airplay.speaker_airplay import SpeakerAirPlay
from miair.airplay.server import AirPlayServer
from miair.dlna.renderer import DLNARenderer


def _controller():
    speaker = SimpleNamespace(
        hardware="test",
        get_dlna_name=lambda: "Living",
    )
    return SimpleNamespace(
        did="living",
        speaker=speaker,
        play_url=AsyncMock(return_value=True),
        pause=AsyncMock(return_value=True),
        stop=AsyncMock(return_value=True),
        set_volume=AsyncMock(return_value=True),
    )


def test_airplay_server_allows_only_one_stateful_client_per_target():
    server = AirPlayServer("127.0.0.1", "Living")
    first = object()
    second = object()

    assert server._claim_client(first, ("192.0.2.10", 7000)) is True
    assert server._claim_client(second, ("192.0.2.11", 7001)) is False
    assert server._release_client(second) is False
    assert server._release_client(first) is True
    assert server._claim_client(second, ("192.0.2.11", 7001)) is True


@pytest.mark.asyncio
async def test_stale_airplay_stop_cannot_stop_new_protocol_output():
    controller = _controller()
    owns_output = True
    events = []

    async def lifecycle(event, details):
        events.append((event, details))
        return "airplay-session" if event == "session_started" else None

    wrapper = SpeakerAirPlay(
        "127.0.0.1",
        controller,
        config=SimpleNamespace(
            get_device_name=lambda name: name,
            auto_resume_on_interrupt=False,
            default_volume=0,
            follow_device_volume=False,
        ),
        lifecycle_callback=lifecycle,
        output_owner=lambda _session_id: owns_output,
    )

    await wrapper._play_on_speaker("http://127.0.0.1/airplay")
    owns_output = False
    await wrapper._stop_speaker()

    controller.play_url.assert_awaited_once()
    controller.stop.assert_not_awaited()
    assert [event for event, _details in events] == [
        "session_started",
        "media_started",
        "session_ended",
    ]


@pytest.mark.asyncio
async def test_old_airplay_client_callback_cannot_stop_new_airplay_client():
    controller = _controller()
    sessions = iter(["airplay-one", "airplay-two"])

    async def lifecycle(event, _details):
        return next(sessions) if event == "session_started" else None

    wrapper = SpeakerAirPlay(
        "127.0.0.1",
        controller,
        config=SimpleNamespace(
            get_device_name=lambda name: name,
            auto_resume_on_interrupt=False,
            default_volume=0,
            follow_device_volume=False,
        ),
        lifecycle_callback=lifecycle,
    )
    first_token = object()
    second_token = object()
    await wrapper._play_on_speaker("http://127.0.0.1/one", first_token)
    await wrapper._play_on_speaker("http://127.0.0.1/two", second_token)

    await wrapper._stop_speaker(first_token)

    controller.stop.assert_not_awaited()
    assert wrapper._session_id == "airplay-two"
    assert wrapper._source_token is second_token


@pytest.mark.asyncio
async def test_stale_dlna_stop_cannot_stop_new_protocol_output():
    controller = _controller()
    owns_output = True
    events = []

    async def lifecycle(event, details):
        events.append((event, details))
        return "dlna-session" if event == "session_started" else None

    renderer = DLNARenderer(
        "uuid:living",
        "Living",
        controller,
        config=SimpleNamespace(follow_device_volume=True),
        lifecycle_callback=lifecycle,
        output_owner=lambda _session_id: owns_output,
    )
    await renderer.set_av_transport_uri("https://example.test/track.mp3")
    assert await renderer.play() is True

    owns_output = False
    assert await renderer.stop() is True

    controller.play_url.assert_awaited_once()
    controller.stop.assert_not_awaited()
    assert [event for event, _details in events] == [
        "session_started",
        "media_started",
        "session_ended",
    ]
