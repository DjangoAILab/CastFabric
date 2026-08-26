import hashlib

import pytest

from miair.miplay.protocol import (
    Command,
    CommandFrame,
    CommandFrameBuffer,
    OpenDeviceRequest,
    ProtocolError,
    decode_device_info,
    decode_scalar,
    encode_command,
    encode_device_info,
    encode_scalar,
    legacy_challenge_response,
)


def test_command_frame_round_trip_and_incremental_buffering():
    wire = encode_command(Command.GET_DEVICE_INFO, 0x42, b"payload")
    decoder = CommandFrameBuffer()

    assert decoder.feed(wire[:4]) == []
    assert decoder.feed(wire[4:10]) == []
    assert decoder.feed(wire[10:]) == [
        CommandFrame(Command.GET_DEVICE_INFO, 0x42, b"payload")
    ]


def test_command_buffer_splits_coalesced_frames():
    first = encode_command(Command.HEARTBEAT, 1, b"")
    second = encode_command(Command.GET_STATE, 2, b"")

    assert CommandFrameBuffer().feed(first + second) == [
        CommandFrame(Command.HEARTBEAT, 1, b""),
        CommandFrame(Command.GET_STATE, 2, b""),
    ]


def test_command_buffer_rejects_invalid_magic_and_oversized_payload():
    with pytest.raises(ProtocolError, match="magic"):
        CommandFrameBuffer().feed(b"!" + b"\0" * 8)

    decoder = CommandFrameBuffer(max_payload=4)
    with pytest.raises(ProtocolError, match="payload"):
        decoder.feed(encode_command(Command.GET_STATE, 1, b"12345"))


def test_legacy_challenge_response_matches_recovered_vector():
    assert legacy_challenge_response(b"legacy-challenge") == (
        b"1bfbbecf1244c16add4362959aa0ccc7b6e8a0c4"
    )


def test_scalar_and_device_info_codecs_round_trip():
    assert decode_scalar(encode_scalar(38)) == 38
    fields = {
        "name": "OpenXiaoCast",
        "model": "openxiaocast.gateway",
        "support": "audio",
    }
    assert decode_device_info(encode_device_info(fields)) == fields


def test_device_info_decoder_rejects_truncation():
    payload = encode_device_info({"name": "OpenXiaoCast"})
    with pytest.raises(ProtocolError, match="length"):
        decode_device_info(payload[:-1])


def test_open_device_request_requires_ipv4_wfd_url_and_nul():
    request = OpenDeviceRequest.parse(
        b"wfd://192.168.31.8:7274?mirrorMode=1\0"
    )
    assert request.host == "192.168.31.8"
    assert request.port == 7274
    assert request.mirror_mode == 1

    with pytest.raises(ProtocolError, match="NUL"):
        OpenDeviceRequest.parse(b"wfd://192.168.31.8:7274?mirrorMode=1")

    modern = OpenDeviceRequest.parse(
        b"wfd://192.168.31.8:7274?mirrorMode=1",
        allow_missing_nul=True,
    )
    assert modern == request
