"""Bounded receiver support for MiPlay's modern SafetyData control channel."""

from __future__ import annotations

import hashlib
import hmac
import json
import struct
import time
from dataclasses import dataclass

from Crypto.Cipher import AES

from .protocol import Command, CommandFrame, CommandFrameBuffer, ProtocolError, encode_command


_SAFETY_VALUE_TYPE = 30
_HEADER = struct.Struct(">HBBBI")
_FLAGS = 0xE0
_SELECTION = {
    "result": "0",
    "authKeyType": "1",
    "authAlgorithmType": "4",
    "integrityType": "1",
    "aesKeyType": "1",
    "aesIvType": "2",
}


def _json_bytes(value: dict[str, str]) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def encode_envelope(payload: bytes, *, acknowledgement: bool = False) -> bytes:
    tag = b"ack" if acknowledgement else b"cmd"
    return bytes([len(tag)]) + tag + bytes([_SAFETY_VALUE_TYPE]) + struct.pack(">I", len(payload)) + payload


def decode_envelope(data: bytes, *, acknowledgement: bool | None = None) -> bytes:
    if len(data) < 9:
        raise ProtocolError("Safety envelope is truncated")
    tag_length = data[0]
    header_length = 1 + tag_length + 1 + 4
    if len(data) < header_length:
        raise ProtocolError("Safety envelope header is truncated")
    tag = data[1 : 1 + tag_length]
    if tag not in {b"cmd", b"ack"}:
        raise ProtocolError("Safety envelope tag is invalid")
    is_ack = tag == b"ack"
    if acknowledgement is not None and is_ack != acknowledgement:
        raise ProtocolError("Safety envelope direction is invalid")
    if data[1 + tag_length] != _SAFETY_VALUE_TYPE:
        raise ProtocolError("Safety envelope value type is unsupported")
    payload_length = struct.unpack(">I", data[2 + tag_length : header_length])[0]
    if payload_length > 4 * 1024 * 1024 or len(data) != header_length + payload_length:
        raise ProtocolError("Safety envelope length is invalid")
    return data[header_length:]


def derive_type1_auth_key(
    local_endpoint: tuple[str, int], peer_endpoint: tuple[str, int]
) -> bytes:
    material = f"{local_endpoint[0]}{local_endpoint[1]}{peer_endpoint[0]}{peer_endpoint[1]}"
    translated = material.translate(str.maketrans("0123456789", "abcdefghij"))
    return hashlib.md5(translated.encode("utf-8")).hexdigest().encode("ascii")


def crc32_mpeg2(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for value in data:
        crc ^= value << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def native_integrity(data: bytes) -> int:
    return int.from_bytes(crc32_mpeg2(data).to_bytes(4, "big")[::-1], "big")


class SafetyCipher:
    """Stateful AES-CBC codec with independent instances per wire direction."""

    def __init__(self, key: bytes, iv: bytes):
        if len(key) != 16 or len(iv) != 16:
            raise ValueError("SafetyData requires a 16-byte AES key and IV")
        self._key = bytes(key)
        self._iv = bytes(iv)

    def encrypt(self, plaintext: bytes) -> bytes:
        padding = 16 - len(plaintext) % 16
        padded = plaintext + b"\0" * padding
        ciphertext = AES.new(self._key, AES.MODE_CBC, self._iv).encrypt(padded)
        self._iv = ciphertext[-16:]
        return _HEADER.pack(7, 1, _FLAGS, padding, native_integrity(ciphertext)) + ciphertext

    def decrypt(self, data: bytes) -> bytes:
        if len(data) < _HEADER.size + 16:
            raise ProtocolError("SafetyData is truncated")
        header_length, version, flags, padding, integrity = _HEADER.unpack_from(data)
        ciphertext = data[_HEADER.size :]
        if (
            header_length != 7
            or version != 1
            or flags != _FLAGS
            or not 1 <= padding <= 16
            or len(ciphertext) % 16
            or native_integrity(ciphertext) != integrity
        ):
            raise ProtocolError("SafetyData header or integrity is invalid")
        plaintext = AES.new(self._key, AES.MODE_CBC, self._iv).decrypt(ciphertext)
        if padding > len(plaintext) or plaintext[-padding:] != b"\0" * padding:
            raise ProtocolError("SafetyData padding is invalid")
        self._iv = ciphertext[-16:]
        return plaintext[:-padding]


def _decode_json(payload: bytes) -> dict:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Safety payload is not JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Safety payload is not an object")
    return value


def _mask(value: object, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"SafetyInfo {field} is invalid") from exc
    if not 0 <= result <= 0xFFFFFFFF:
        raise ProtocolError(f"SafetyInfo {field} is out of range")
    return result


@dataclass(slots=True)
class SafetyResult:
    writes: list[bytes]
    plaintext: CommandFrame | None = None


class ModernSafetyReceiver:
    """One modern MiPlay mutual-auth and encrypted business-command session."""

    def __init__(self, local_endpoint: tuple[str, int], peer_endpoint: tuple[str, int]):
        self.auth_key = derive_type1_auth_key(local_endpoint, peer_endpoint)
        key = self.auth_key[:16]
        nominal_iv = self.auth_key[16:]
        # Real Xiaomi receiver captures use the type-1 material as the initial
        # outbound IV even after selecting aesIvType=2.  Phone sources mirror
        # that native quirk when decrypting a receiver challenge.
        self._encrypt = SafetyCipher(key, key)
        # Some released senders label type-2 while using the type-1 IV inbound.
        self._decrypt_candidates = {
            "type-2": SafetyCipher(key, nominal_iv),
            "type-1-compat": SafetyCipher(key, key),
        }
        self._decrypt: SafetyCipher | None = None
        self.inbound_iv_mode: str | None = None
        self.local_auth_message: str | None = None
        self.peer_auth_message: str | None = None
        self.peer_auth_sequence: int | None = None
        self.auth_key_mode: str | None = None
        self.peer_ack_shape: str | None = None
        self.peer_ack_result: str | None = None
        self.peer_challenge_acknowledged = False
        self.local_challenge_verified = False
        self.phase = "created"

    @property
    def mutual_auth_complete(self) -> bool:
        return self.peer_challenge_acknowledged and self.local_challenge_verified

    def diagnostics(self) -> dict[str, str | bool | None]:
        return {
            "phase": self.phase,
            "mutual_auth_complete": self.mutual_auth_complete,
            "inbound_iv_mode": self.inbound_iv_mode,
            "outbound_iv_mode": "type-1-compat",
            "auth_key_mode": self.auth_key_mode,
            "peer_ack_shape": self.peer_ack_shape,
            "peer_ack_result": self.peer_ack_result,
        }

    def accept_info(self, frame: CommandFrame) -> SafetyResult:
        if self.phase != "created" or frame.command != Command.SAFETY_INFO:
            raise ProtocolError("unexpected SafetyInfo command")
        offer = _decode_json(decode_envelope(frame.payload, acknowledgement=False))
        required = {
            "authKeyTypes": 1,
            "authAlgorithmTypes": 4,
            "integrityTypes": 1,
            "aesKeyTypes": 1,
            "aesIvTypes": 2,
        }
        for field, selected in required.items():
            if _mask(offer.get(field), field) & selected != selected:
                raise ProtocolError("SafetyInfo offer does not support receiver selection")

        timestamp_us = time.time_ns() // 1000
        self.local_auth_message = hashlib.md5(str(timestamp_us).encode("ascii")).hexdigest()
        selection = encode_envelope(_json_bytes(_SELECTION), acknowledgement=True)
        challenge = encode_envelope(_json_bytes({"authMsg": self.local_auth_message}))
        self.phase = "awaiting-mutual-auth"
        return SafetyResult(
            [
                encode_command(Command.SAFETY_INFO_ACK, frame.sequence, selection),
                encode_command(Command.SAFETY_AUTH, 0, self._encrypt.encrypt(challenge)),
            ]
        )

    def process(self, frame: CommandFrame) -> SafetyResult:
        if frame.command == Command.SAFETY_AUTH:
            if self.peer_challenge_acknowledged:
                raise ProtocolError("duplicate peer SafetyAuth challenge")
            payload = self._decrypt_envelope(frame.payload, acknowledgement=False)
            challenge = _decode_json(payload).get("authMsg")
            if not isinstance(challenge, str) or len(challenge) != 32:
                raise ProtocolError("peer SafetyAuth challenge is invalid")
            self.peer_auth_message = challenge
            self.peer_auth_sequence = frame.sequence
            digest = self._auth_digest(challenge, "ascii-full")
            ack = encode_envelope(
                _json_bytes({"result": "0", "authMsgAck": digest}),
                acknowledgement=True,
            )
            self.peer_challenge_acknowledged = True
            self._update_phase()
            return SafetyResult(
                [encode_command(Command.SAFETY_AUTH_ACK, frame.sequence, self._encrypt.encrypt(ack))]
            )

        if frame.command == Command.SAFETY_AUTH_ACK:
            if self.local_auth_message is None or self.local_challenge_verified:
                raise ProtocolError("unsolicited or duplicate SafetyAuth acknowledgement")
            payload = self._decrypt_envelope(frame.payload, acknowledgement=True)
            value = _decode_json(payload)
            self.peer_ack_result = str(value.get("result"))
            received = value.get("authMsgAck")
            if not isinstance(received, str):
                self.peer_ack_shape = "non-string"
            elif len(received) == 64 and all(char in "0123456789abcdef" for char in received):
                self.peer_ack_shape = "lower-hex-64"
            elif len(received) == 64 and all(char in "0123456789ABCDEF" for char in received):
                self.peer_ack_shape = "upper-hex-64"
            else:
                self.peer_ack_shape = f"other-{len(received)}"
            mode = self._match_auth_ack(received) if isinstance(received, str) else None
            if str(value.get("result")) not in {"0", "1"} or mode is None:
                raise ProtocolError("peer SafetyAuth acknowledgement failed verification")
            self.auth_key_mode = mode
            self.local_challenge_verified = True
            self._update_phase()
            # The K60 source sends its acknowledgement after receiving our
            # standards-profile acknowledgement.  If it proves that it uses a
            # different native key representation, immediately repeat the peer
            # acknowledgement with that representation and continued CBC state.
            if mode != "ascii-full" and self.peer_auth_message is not None:
                digest = self._auth_digest(self.peer_auth_message, mode)
                ack = encode_envelope(
                    _json_bytes({"result": "0", "authMsgAck": digest}),
                    acknowledgement=True,
                )
                sequence = self.peer_auth_sequence if self.peer_auth_sequence is not None else frame.sequence
                return SafetyResult(
                    [encode_command(Command.SAFETY_AUTH_ACK, sequence, self._encrypt.encrypt(ack))]
                )
            return SafetyResult([])

        if not self.mutual_auth_complete:
            raise ProtocolError("business command arrived before mutual SafetyAuth")
        plaintext = self._decrypt_payload(frame.payload)
        return SafetyResult([], CommandFrame(frame.command, frame.sequence, plaintext))

    def wrap_writes(self, writes: list[bytes]) -> list[bytes]:
        wrapped: list[bytes] = []
        for wire in writes:
            decoder = CommandFrameBuffer()
            frames = decoder.feed(wire)
            if len(frames) != 1:
                raise ProtocolError("outbound command encoding is incomplete")
            frame = frames[0]
            wrapped.append(
                encode_command(frame.command, frame.sequence, self._encrypt.encrypt(frame.payload))
            )
        return wrapped

    def _decrypt_payload(self, payload: bytes) -> bytes:
        if self._decrypt is None:
            raise ProtocolError("SafetyData inbound cipher is not selected")
        return self._decrypt.decrypt(payload)

    def _decrypt_envelope(self, payload: bytes, *, acknowledgement: bool) -> bytes:
        if self._decrypt is not None:
            return decode_envelope(self._decrypt.decrypt(payload), acknowledgement=acknowledgement)
        errors = []
        for mode, cipher in self._decrypt_candidates.items():
            try:
                plaintext = cipher.decrypt(payload)
                decoded = decode_envelope(plaintext, acknowledgement=acknowledgement)
            except ProtocolError as exc:
                errors.append(exc)
                continue
            self._decrypt = cipher
            self.inbound_iv_mode = mode
            self._decrypt_candidates.clear()
            return decoded
        raise ProtocolError("SafetyAuth payload did not decrypt with supported IV modes") from (errors[-1] if errors else None)

    def _update_phase(self) -> None:
        self.phase = "ready" if self.mutual_auth_complete else "awaiting-mutual-auth"

    def _match_auth_ack(self, received: str) -> str | None:
        assert self.local_auth_message is not None
        for mode in ("ascii-full", "ascii-half", "binary-md5"):
            expected = self._auth_digest(self.local_auth_message, mode)
            if hmac.compare_digest(received.lower(), expected):
                return mode
        return None

    def _auth_digest(self, message: str, mode: str) -> str:
        if mode == "ascii-full":
            key = self.auth_key
        elif mode == "ascii-half":
            key = self.auth_key[:16]
        elif mode == "binary-md5":
            key = bytes.fromhex(self.auth_key.decode("ascii"))
        else:
            raise ValueError("unsupported SafetyAuth key representation")
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
