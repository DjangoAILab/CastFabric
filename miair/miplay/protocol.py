"""Transport-independent codecs for the observed MiPlay legacy protocol."""

from __future__ import annotations

import enum
import hashlib
import hmac
import ipaddress
import re
import struct
from dataclasses import dataclass
from typing import Mapping


MAGIC = 0x24
HEADER = struct.Struct(">BHHI")
MAX_PAYLOAD = 4 * 1024 * 1024
DEVICE_INFO_STRING = 0x0C


class ProtocolError(ValueError):
    """Raised when bytes do not match the bounded MiPlay wire contract."""


class Command(enum.IntEnum):
    OPEN = 0x0000
    CLOSE = 0x0002
    PAUSE = 0x0004
    PAUSE_ACK = 0x0005
    RESUME = 0x0006
    RESUME_ACK = 0x0007
    SET_VOLUME = 0x000C
    SET_VOLUME_ACK = 0x000D
    GET_VOLUME = 0x000E
    GET_VOLUME_ACK = 0x000F
    GET_POSITION = 0x0010
    GET_POSITION_ACK = 0x0011
    SET_MEDIA_INFO = 0x0012
    SET_MEDIA_INFO_ACK = 0x0013
    GET_MEDIA_INFO = 0x0014
    GET_MEDIA_INFO_ACK = 0x0015
    HEARTBEAT = 0x001A
    HEARTBEAT_ACK = 0x001B
    GET_STATE = 0x001C
    GET_STATE_ACK = 0x001D
    GET_DEVICE_INFO = 0x001E
    GET_DEVICE_INFO_ACK = 0x001F
    NOTIFY = 0x0022
    LEGACY_CHALLENGE = 0x0028
    LEGACY_CHALLENGE_ACK = 0x0029
    ADD_MIRROR = 0x002E
    ADD_MIRROR_ACK = 0x002F
    GET_MIRROR_MODE = 0x0034
    GET_MIRROR_MODE_ACK = 0x0035
    SOURCE_VERSION = 0x0036
    SOURCE_VERSION_ACK = 0x0037
    SET_PLAY_SOURCE = 0x0040
    SET_PLAY_SOURCE_ACK = 0x0041
    SET_LOCAL_DEVICE_INFO = 0x0058
    SET_LOCAL_DEVICE_INFO_ACK = 0x0059
    SOURCE_CAPABILITY_UPDATE = 0x0416
    SOURCE_CAPABILITY_UPDATE_ACK = 0x0417
    SAFETY_INFO = 0x1400
    SAFETY_INFO_ACK = 0x1401
    SAFETY_AUTH = 0x1402
    SAFETY_AUTH_ACK = 0x1403


@dataclass(frozen=True, slots=True)
class CommandFrame:
    command: int
    sequence: int
    payload: bytes


def encode_command(command: int, sequence: int, payload: bytes = b"") -> bytes:
    payload = bytes(payload)
    if not 0 <= int(command) <= 0xFFFF:
        raise ProtocolError("command out of range")
    if not 0 <= sequence <= 0xFFFF:
        raise ProtocolError("sequence out of range")
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("payload exceeds safety limit")
    return HEADER.pack(MAGIC, int(command), sequence, len(payload)) + payload


class CommandFrameBuffer:
    """Incrementally split a TCP byte stream into complete command frames."""

    def __init__(self, max_payload: int = MAX_PAYLOAD):
        self.max_payload = max_payload
        self._buffer = bytearray()

    def feed(self, data: bytes | bytearray | memoryview) -> list[CommandFrame]:
        self._buffer.extend(data)
        frames: list[CommandFrame] = []
        while len(self._buffer) >= HEADER.size:
            magic, command, sequence, payload_length = HEADER.unpack_from(self._buffer)
            if magic != MAGIC:
                self._buffer.clear()
                raise ProtocolError("invalid command-frame magic")
            if payload_length > self.max_payload:
                self._buffer.clear()
                raise ProtocolError("command payload exceeds safety limit")
            frame_length = HEADER.size + payload_length
            if len(self._buffer) < frame_length:
                break
            payload = bytes(self._buffer[HEADER.size:frame_length])
            del self._buffer[:frame_length]
            frames.append(CommandFrame(command, sequence, payload))
        return frames


def legacy_challenge_response(challenge: bytes) -> bytes:
    """Return the recovered 0x0029 lowercase HMAC-SHA1 text."""

    legacy_key = hashlib.md5(b"0.0.0.0").hexdigest().encode("ascii")
    return hmac.new(legacy_key, bytes(challenge), hashlib.sha1).hexdigest().encode("ascii")


def encode_scalar(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ProtocolError("scalar out of range")
    return b"\0" + struct.pack(">I", value)


def decode_scalar(payload: bytes) -> int:
    if len(payload) != 5 or payload[0] != 0:
        raise ProtocolError("invalid five-byte scalar")
    return struct.unpack(">I", payload[1:])[0]


def encode_device_info(fields: Mapping[str, str]) -> bytes:
    if not fields:
        raise ProtocolError("device info requires at least one field")
    body = bytearray()
    for name, value in fields.items():
        try:
            name_bytes = name.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ProtocolError("device-info name must be ASCII") from exc
        value_bytes = value.encode("utf-8")
        if not 1 <= len(name_bytes) <= 255:
            raise ProtocolError("device-info name length out of range")
        if len(value_bytes) > 0xFFFF:
            raise ProtocolError("device-info value length out of range")
        body.append(len(name_bytes))
        body.extend(name_bytes)
        body.append(DEVICE_INFO_STRING)
        body.extend(struct.pack(">H", len(value_bytes)))
        body.extend(value_bytes)
    if len(body) > 0xFFFFFF:
        raise ProtocolError("device-info body length out of range")
    return len(body).to_bytes(3, "big") + body


def decode_device_info(payload: bytes) -> dict[str, str]:
    if len(payload) < 3:
        raise ProtocolError("device-info length header is truncated")
    body_length = int.from_bytes(payload[:3], "big")
    if len(payload) != 3 + body_length:
        raise ProtocolError("device-info declared length does not match payload")
    result: dict[str, str] = {}
    offset = 3
    while offset < len(payload):
        name_length = payload[offset]
        offset += 1
        if not name_length or offset + name_length + 3 > len(payload):
            raise ProtocolError("device-info field length is invalid")
        name = payload[offset:offset + name_length].decode("ascii")
        offset += name_length
        if payload[offset] != DEVICE_INFO_STRING:
            raise ProtocolError("unsupported device-info value type")
        offset += 1
        value_length = struct.unpack(">H", payload[offset:offset + 2])[0]
        offset += 2
        if offset + value_length > len(payload):
            raise ProtocolError("device-info value length is truncated")
        if name in result:
            raise ProtocolError("duplicate device-info field")
        result[name] = payload[offset:offset + value_length].decode("utf-8")
        offset += value_length
    return result


_OPEN_RE = re.compile(
    r"^wfd://(?P<host>[^:/?]+):(?P<port>[0-9]+)\?mirrorMode=(?P<mode>[0-9]+)$"
)


@dataclass(frozen=True, slots=True)
class OpenDeviceRequest:
    host: str
    port: int
    mirror_mode: int

    @classmethod
    def parse(
        cls, payload: bytes, *, allow_missing_nul: bool = False
    ) -> "OpenDeviceRequest":
        has_terminator = payload.endswith(b"\0")
        if not has_terminator and not allow_missing_nul:
            raise ProtocolError("Open payload must have one NUL terminator")
        content = payload[:-1] if has_terminator else payload
        if b"\0" in content:
            raise ProtocolError("Open payload contains an embedded NUL")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("Open payload is not UTF-8") from exc
        match = _OPEN_RE.fullmatch(text)
        if not match:
            raise ProtocolError("invalid Open WFD URL")
        try:
            address = ipaddress.ip_address(match.group("host"))
        except ValueError as exc:
            raise ProtocolError("Open WFD host must be an IP address") from exc
        if address.version != 4:
            raise ProtocolError("Open WFD host must be IPv4")
        port = int(match.group("port"))
        mode = int(match.group("mode"))
        if not 1 <= port <= 65535:
            raise ProtocolError("Open WFD port out of range")
        return cls(str(address), port, mode)


def encode_notify_scalar(label: str, value: int) -> bytes:
    label_bytes = label.encode("ascii")
    if not 1 <= len(label_bytes) <= 255 or not 0 <= value <= 255:
        raise ProtocolError("notify scalar out of range")
    return bytes([len(label_bytes)]) + label_bytes + b"\x03" + bytes([value])
