import json

from miair.miplay.control import ControlPhase, LegacyReceiverSession
from miair.miplay.protocol import (
    Command,
    CommandFrame,
    CommandFrameBuffer,
    OpenDeviceRequest,
    decode_device_info,
    decode_scalar,
    encode_command,
    legacy_challenge_response,
)


def decoded(writes):
    decoder = CommandFrameBuffer()
    frames = []
    for write in writes:
        frames.extend(decoder.feed(write))
    return frames


def authenticated_session():
    session = LegacyReceiverSession(challenge=b"123456789012345")
    challenge = decoded(session.start())[0]
    assert challenge.command == Command.LEGACY_CHALLENGE

    version = session.process(
        CommandFrame(Command.SOURCE_VERSION, 0, b"1.0.1123012\0")
    )
    assert decoded(version.writes)[0].command == Command.SOURCE_VERSION_ACK

    auth = session.process(
        CommandFrame(
            Command.LEGACY_CHALLENGE_ACK,
            challenge.sequence,
            legacy_challenge_response(challenge.payload),
        )
    )
    assert auth.accepted
    assert session.authenticated
    return session


def test_complete_legacy_receiver_transcript_reaches_open():
    session = authenticated_session()

    device_info = session.process(CommandFrame(Command.GET_DEVICE_INFO, 1, b""))
    frame = decoded(device_info.writes)[0]
    assert frame.command == Command.GET_DEVICE_INFO_ACK
    assert frame.sequence == 1
    assert decode_device_info(frame.payload)["support"] == "audio"

    source_name = session.process(
        CommandFrame(
            Command.SET_LOCAL_DEVICE_INFO,
            2,
            json.dumps({"sourceName": "Offline MiPlay Source"}).encode(),
        )
    )
    assert decoded(source_name.writes) == [
        CommandFrame(Command.SET_LOCAL_DEVICE_INFO_ACK, 2, b"")
    ]

    mirror = session.process(CommandFrame(Command.GET_MIRROR_MODE, 4, b""))
    assert decode_scalar(decoded(mirror.writes)[0].payload) == 2

    volume = session.process(CommandFrame(Command.GET_VOLUME, 5, b""))
    assert decode_scalar(decoded(volume.writes)[0].payload) == 38

    state = session.process(CommandFrame(Command.GET_STATE, 7, b""))
    assert decode_scalar(decoded(state.writes)[0].payload) == 3

    heartbeat = session.process(CommandFrame(Command.HEARTBEAT, 12, b""))
    assert decoded(heartbeat.writes)[0] == CommandFrame(
        Command.HEARTBEAT_ACK, 12, b""
    )

    set_source = session.process(
        CommandFrame(Command.SET_PLAY_SOURCE, 13, b'{"ref_channel":"system"}')
    )
    assert set_source.accepted
    assert set_source.writes == []

    opened = session.process(
        CommandFrame(
            Command.OPEN,
            14,
            b"wfd://127.0.0.1:37274?mirrorMode=1\0",
        )
    )
    assert opened.open_request == OpenDeviceRequest("127.0.0.1", 37274, 1)
    assert session.phase == ControlPhase.OPENED


def test_wrong_or_duplicate_auth_stops_session_without_echoing_secrets():
    session = LegacyReceiverSession(challenge=b"123456789012")
    session.start()
    rejected = session.process(
        CommandFrame(Command.LEGACY_CHALLENGE_ACK, 0, b"wrong")
    )

    assert not rejected.accepted
    assert session.phase == ControlPhase.STOPPED
    assert "wrong" not in repr(session.diagnostics)


def test_open_before_auth_and_safety_without_endpoint_context_are_rejected_cleanly():
    early = LegacyReceiverSession(challenge=b"123456789012")
    early.start()
    result = early.process(
        CommandFrame(Command.OPEN, 1, b"wfd://127.0.0.1:7274?mirrorMode=1\0")
    )
    assert not result.accepted
    assert "authentication" in result.reason

    safety = LegacyReceiverSession(challenge=b"123456789012")
    safety.start()
    result = safety.process(CommandFrame(Command.SAFETY_INFO, 1, b"sensitive"))
    assert not result.accepted
    assert result.reason == "SafetyInfo arrived before legacy authentication"
    assert safety.diagnostics[-1]["payload_bytes"] == 9
    assert "sensitive" not in repr(safety.diagnostics)


def test_media_started_notifications_are_emitted_once():
    session = authenticated_session()
    session.process(CommandFrame(Command.SET_PLAY_SOURCE, 13, b"{}"))
    session.process(
        CommandFrame(Command.OPEN, 14, b"wfd://127.0.0.1:7274?mirrorMode=1\0")
    )

    first = decoded(session.media_started())
    second = session.media_started()

    assert [frame.command for frame in first] == [Command.NOTIFY, Command.NOTIFY]
    assert b"first-audiopcm" in first[0].payload
    assert b"state" in first[1].payload
    assert second == []


def test_current_miui_source_capability_update_is_non_fatal():
    session = authenticated_session()

    result = session.process(
        CommandFrame(Command.SOURCE_CAPABILITY_UPDATE, 15, b'{"capability":1}')
    )

    assert result.accepted
    assert result.writes == []
    assert session.phase == ControlPhase.READY
