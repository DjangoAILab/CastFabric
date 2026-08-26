import hashlib
import hmac
import json

import pytest

from miair.miplay.control import LegacyReceiverSession
from miair.miplay.protocol import (
    Command,
    CommandFrame,
    CommandFrameBuffer,
    ProtocolError,
    decode_device_info,
    legacy_challenge_response,
)
from miair.miplay.safety import (
    ModernSafetyReceiver,
    SafetyCipher,
    crc32_mpeg2,
    decode_envelope,
    derive_type1_auth_key,
    encode_envelope,
)


def _decode(writes):
    decoder = CommandFrameBuffer()
    frames = []
    for write in writes:
        frames.extend(decoder.feed(write))
    return frames


def _json(payload):
    return json.loads(payload.decode("utf-8"))


def test_safety_envelope_and_key_derivation_vectors():
    payload = b'{"authMsg":"value"}'
    encoded = encode_envelope(payload)
    assert decode_envelope(encoded, acknowledgement=False) == payload
    assert decode_envelope(encode_envelope(payload, acknowledgement=True), acknowledgement=True) == payload
    assert derive_type1_auth_key(
        ("192.168.10.7", 8899), ("192.168.10.20", 43720)
    ) == b"a565e5251cce7d9995e34b18bb656c33"


def test_safety_cipher_is_stateful_and_rejects_tampering():
    key = b"0123456789abcdef"
    iv = b"fedcba9876543210"
    encryptor = SafetyCipher(key, iv)
    decryptor = SafetyCipher(key, iv)
    for plaintext in (b"first", b"second payload", b""):
        wire = encryptor.encrypt(plaintext)
        assert decryptor.decrypt(wire) == plaintext

    damaged = bytearray(SafetyCipher(key, iv).encrypt(b"tamper"))
    damaged[-1] ^= 1
    with pytest.raises(ProtocolError, match="integrity"):
        SafetyCipher(key, iv).decrypt(bytes(damaged))
    assert crc32_mpeg2(b"123456789") == 0x0376E6E7


@pytest.mark.parametrize(
    ("mode", "key_factory"),
    [
        ("ascii-full", lambda value: value),
        ("ascii-half", lambda value: value[:16]),
        ("binary-md5", lambda value: bytes.fromhex(value.decode("ascii"))),
    ],
)
def test_safety_auth_recognizes_native_key_representations(mode, key_factory):
    receiver = ModernSafetyReceiver(
        ("192.168.133.5", 8899), ("192.168.133.225", 43720)
    )
    receiver.local_auth_message = "0123456789abcdef0123456789abcdef"
    received = hmac.new(
        key_factory(receiver.auth_key),
        receiver.local_auth_message.encode(),
        hashlib.sha256,
    ).hexdigest()
    assert receiver._match_auth_ack(received) == mode


def test_modern_safety_mutual_auth_then_encrypted_business_command():
    local = ("192.168.133.5", 8899)
    peer = ("192.168.133.225", 43720)
    session = LegacyReceiverSession(
        challenge=b"123456789012345",
        local_endpoint=local,
        peer_endpoint=peer,
    )
    challenge = _decode(session.start())[0]
    assert session.process(
        CommandFrame(
            Command.LEGACY_CHALLENGE_ACK,
            challenge.sequence,
            legacy_challenge_response(challenge.payload),
        )
    ).accepted

    offer = {
        "authKeyTypes": "1",
        "authAlgorithmTypes": "7",
        "integrityTypes": "1",
        "aesKeyTypes": "1",
        "aesIvTypes": "3",
    }
    negotiated = session.process(
        CommandFrame(Command.SAFETY_INFO, 9, encode_envelope(json.dumps(offer).encode()))
    )
    info_ack, receiver_challenge = _decode(negotiated.writes)
    assert info_ack.command == Command.SAFETY_INFO_ACK
    assert info_ack.sequence == 9
    assert _json(decode_envelope(info_ack.payload, acknowledgement=True))["authAlgorithmType"] == "4"

    auth_key = derive_type1_auth_key(local, peer)
    phone_inbound = SafetyCipher(auth_key[:16], auth_key[:16])
    phone_outbound = SafetyCipher(auth_key[:16], auth_key[16:])
    local_challenge = _json(
        decode_envelope(phone_inbound.decrypt(receiver_challenge.payload), acknowledgement=False)
    )["authMsg"]

    peer_message = hashlib.md5(b"phone timestamp").hexdigest()
    peer_challenge = phone_outbound.encrypt(
        encode_envelope(json.dumps({"authMsg": peer_message}).encode())
    )
    acknowledged = session.process(CommandFrame(Command.SAFETY_AUTH, 10, peer_challenge))
    ack_frame = _decode(acknowledged.writes)[0]
    ack = _json(decode_envelope(phone_inbound.decrypt(ack_frame.payload), acknowledgement=True))
    assert ack["authMsgAck"] == hmac.new(
        auth_key, peer_message.encode(), hashlib.sha256
    ).hexdigest()

    local_ack = hmac.new(auth_key, local_challenge.encode(), hashlib.sha256).hexdigest()
    result = session.process(
        CommandFrame(
            Command.SAFETY_AUTH_ACK,
            0,
            phone_outbound.encrypt(
                encode_envelope(
                    json.dumps({"result": "1", "authMsgAck": local_ack}).encode(),
                    acknowledgement=True,
                )
            ),
        )
    )
    assert result.accepted
    assert session.safety_diagnostics()["mutual_auth_complete"] is True

    response = session.process(
        CommandFrame(Command.GET_DEVICE_INFO, 11, phone_outbound.encrypt(b""))
    )
    encrypted_response = _decode(response.writes)[0]
    assert encrypted_response.command == Command.GET_DEVICE_INFO_ACK
    assert decode_device_info(phone_inbound.decrypt(encrypted_response.payload))["support"] == "audio"

    opened = session.process(
        CommandFrame(
            Command.OPEN,
            12,
            phone_outbound.encrypt(b"wfd://192.168.133.225:7274?mirrorMode=1"),
        )
    )
    assert opened.accepted
    assert opened.open_request is not None
