"""Incremental RTSP codec and receiver half of the MiPlay WFD handshake."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .protocol import ProtocolError


MAX_RTSP_MESSAGE = 256 * 1024
WFD_TARGET = "rtsp://localhost/wfd1.0"


@dataclass(slots=True)
class RtspMessage:
    start_line: str
    headers: dict[str, str]
    body: bytes = b""

    def __post_init__(self) -> None:
        self.body = bytes(self.body)
        if self.body and self.header("Content-Length") is None:
            self.headers["Content-Length"] = str(len(self.body))

    def header(self, name: str) -> str | None:
        lowered = name.casefold()
        for key, value in self.headers.items():
            if key.casefold() == lowered:
                return value
        return None


def encode_rtsp(message: RtspMessage) -> bytes:
    if "\r" in message.start_line or "\n" in message.start_line:
        raise ProtocolError("invalid RTSP start line")
    lines = [message.start_line]
    saw_length = False
    for name, value in message.headers.items():
        if any(character in name + value for character in "\r\n"):
            raise ProtocolError("invalid RTSP header")
        if name.casefold() == "content-length":
            saw_length = True
            value = str(len(message.body))
        lines.append(f"{name}: {value}")
    if message.body and not saw_length:
        lines.append(f"Content-Length: {len(message.body)}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + message.body


class RtspBuffer:
    def __init__(self, maximum: int = MAX_RTSP_MESSAGE):
        self.maximum = maximum
        self._buffer = bytearray()

    def feed(self, data: bytes | bytearray | memoryview) -> list[RtspMessage]:
        self._buffer.extend(data)
        if len(self._buffer) > self.maximum:
            self._buffer.clear()
            raise ProtocolError("RTSP input exceeds safety limit")
        result: list[RtspMessage] = []
        while True:
            header_end = self._buffer.find(b"\r\n\r\n")
            if header_end < 0:
                break
            try:
                head = self._buffer[:header_end].decode("ascii")
            except UnicodeDecodeError as exc:
                self._buffer.clear()
                raise ProtocolError("RTSP headers are not ASCII") from exc
            lines = head.split("\r\n")
            if not lines or not lines[0]:
                raise ProtocolError("RTSP start line is empty")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" not in line:
                    raise ProtocolError("malformed RTSP header")
                name, value = line.split(":", 1)
                name, value = name.strip(), value.strip()
                if not name or name.casefold() in {
                    item.casefold() for item in headers
                }:
                    raise ProtocolError("duplicate or empty RTSP header")
                headers[name] = value
            length_text = next(
                (value for key, value in headers.items() if key.casefold() == "content-length"),
                "0",
            )
            try:
                body_length = int(length_text)
            except ValueError as exc:
                raise ProtocolError("invalid RTSP Content-Length") from exc
            if body_length < 0 or body_length > self.maximum:
                raise ProtocolError("RTSP body exceeds safety limit")
            message_length = header_end + 4 + body_length
            if len(self._buffer) < message_length:
                break
            body = bytes(self._buffer[header_end + 4:message_length])
            del self._buffer[:message_length]
            result.append(RtspMessage(lines[0], headers, body))
        return result


class RtspPhase(enum.Enum):
    AWAITING_SOURCE_OPTIONS = "awaiting_source_options"
    AWAITING_OPTIONS_ACK = "awaiting_options_ack"
    AWAITING_CAPABILITY_QUERY = "awaiting_capability_query"
    AWAITING_SELECTED_PARAMETERS = "awaiting_selected_parameters"
    AWAITING_SETUP_TRIGGER = "awaiting_setup_trigger"
    AWAITING_SETUP_ACK = "awaiting_setup_ack"
    AWAITING_PLAY_ACK = "awaiting_play_ack"
    AWAITING_TIME_OFFSET = "awaiting_time_offset"
    READY = "ready"
    STOPPED = "stopped"


@dataclass(slots=True)
class RtspTransition:
    accepted: bool
    writes: list[bytes]
    reason: str
    ready: bool = False


class ReceiverRtspSession:
    """The receiver role for the captured AAC-only reverse WFD session."""

    CAPABILITIES = (
        b"wfd_video_formats: none\r\n"
        b"wfd_audio_codecs: AAC 00000001 00\r\n"
        b"wfd_client_rtp_ports: RTP/AVP/TCP;interleaved mode=play\r\n"
        b"wfd_tcp_enable: 1\r\n"
    )

    def __init__(self, source_address: str):
        self.source_address = source_address
        self.phase = RtspPhase.AWAITING_SOURCE_OPTIONS
        self.session_id: str | None = None
        self.time_offset_us: int | None = None
        self.timer_endpoint: tuple[str, int] | None = None

    def process(self, message: RtspMessage) -> RtspTransition:
        if self.phase is RtspPhase.STOPPED:
            return RtspTransition(False, [], "RTSP session is stopped")
        try:
            if self.phase is RtspPhase.AWAITING_SOURCE_OPTIONS:
                return self._source_options(message)
            if self.phase is RtspPhase.AWAITING_OPTIONS_ACK:
                return self._options_ack(message)
            if self.phase is RtspPhase.AWAITING_CAPABILITY_QUERY:
                return self._capability_query(message)
            if self.phase is RtspPhase.AWAITING_SELECTED_PARAMETERS:
                return self._selected_parameters(message)
            if self.phase is RtspPhase.AWAITING_SETUP_TRIGGER:
                return self._setup_trigger(message)
            if self.phase is RtspPhase.AWAITING_SETUP_ACK:
                return self._setup_ack(message)
            if self.phase is RtspPhase.AWAITING_PLAY_ACK:
                return self._play_ack(message)
            if self.phase is RtspPhase.AWAITING_TIME_OFFSET:
                return self._time_offset(message)
            if self.phase is RtspPhase.READY:
                return self._ready_request(message)
        except ProtocolError as exc:
            return self._stop(str(exc))
        return self._stop("unsupported RTSP phase")

    def _source_options(self, message: RtspMessage) -> RtspTransition:
        self._require_request(message, "OPTIONS", 1)
        timer = message.header("wfd_timer_server_port")
        if timer:
            try:
                address_value, port_value = timer.split(":", 1)
                value = int(address_value)
                address = ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))
                self.timer_endpoint = (address, int(port_value))
            except (ValueError, TypeError) as exc:
                raise ProtocolError("invalid WFD timer endpoint") from exc
        response = self._response(1)
        receiver_options = RtspMessage(
            "OPTIONS * RTSP/1.0",
            {
                "CSeq": "1",
                "Require": "org.wfa.wfd1.0",
                "lib_version": "audio-speaker-mico-cloud 2.1.5091615",
            },
        )
        self.phase = RtspPhase.AWAITING_OPTIONS_ACK
        return self._ok([response, receiver_options], "bidirectional OPTIONS started")

    def _options_ack(self, message: RtspMessage) -> RtspTransition:
        self._require_response(message, 1)
        self.phase = RtspPhase.AWAITING_CAPABILITY_QUERY
        return self._ok([], "receiver OPTIONS acknowledged")

    def _capability_query(self, message: RtspMessage) -> RtspTransition:
        self._require_request(message, "GET_PARAMETER", 2)
        self.phase = RtspPhase.AWAITING_SELECTED_PARAMETERS
        return self._ok(
            [self._response(2, self.CAPABILITIES)],
            "AAC-only receiver capabilities returned",
        )

    def _selected_parameters(self, message: RtspMessage) -> RtspTransition:
        self._require_request(message, "SET_PARAMETER", 3)
        if b"wfd_audio_codecs: AAC 00000001 00" not in message.body or b"RTP/AVP/TCP" not in message.body:
            raise ProtocolError("source did not select the AAC interleaved profile")
        self.phase = RtspPhase.AWAITING_SETUP_TRIGGER
        return self._ok([self._response(3)], "selected parameters accepted")

    def _setup_trigger(self, message: RtspMessage) -> RtspTransition:
        self._require_request(message, "SET_PARAMETER", 4)
        if b"wfd_trigger_method: SETUP" not in message.body:
            raise ProtocolError("SET_PARAMETER did not contain the SETUP trigger")
        target = f"rtsp://{self.source_address}/wfd1.0/streamid=0"
        setup = RtspMessage(
            f"SETUP {target} RTSP/1.0",
            {"CSeq": "2", "Transport": "RTP/AVP/TCP;interleaved=0-1"},
        )
        self.phase = RtspPhase.AWAITING_SETUP_ACK
        return self._ok([self._response(4), setup], "SETUP requested")

    def _setup_ack(self, message: RtspMessage) -> RtspTransition:
        self._require_response(message, 2)
        session_header = message.header("Session")
        if not session_header:
            raise ProtocolError("SETUP response omitted Session")
        session_id = session_header.split(";", 1)[0].strip()
        if not session_id.isdigit():
            raise ProtocolError("SETUP Session is not decimal")
        self.session_id = session_id
        target = f"rtsp://{self.source_address}/wfd1.0/streamid=0"
        play = RtspMessage(
            f"PLAY {target} RTSP/1.0",
            {"CSeq": "3", "Session": session_id},
        )
        self.phase = RtspPhase.AWAITING_PLAY_ACK
        return self._ok([play], "PLAY requested")

    def _play_ack(self, message: RtspMessage) -> RtspTransition:
        self._require_response(message, 3)
        self.phase = RtspPhase.AWAITING_TIME_OFFSET
        return self._ok([], "PLAY acknowledged")

    def _time_offset(self, message: RtspMessage) -> RtspTransition:
        self._require_request(message, "TIME_OFFSET", 5)
        value = message.header("TimeOffset")
        try:
            self.time_offset_us = int(value or "")
        except ValueError as exc:
            raise ProtocolError("TIME_OFFSET omitted a numeric TimeOffset") from exc
        self.phase = RtspPhase.READY
        return self._ok([self._response(5)], "WFD session ready", ready=True)

    def _ready_request(self, message: RtspMessage) -> RtspTransition:
        method = message.start_line.split(" ", 1)[0]
        cseq = self._cseq(message)
        if method in {"OPTIONS", "GET_PARAMETER", "SET_PARAMETER"}:
            return self._ok([self._response(cseq)], f"{method} keepalive acknowledged", ready=True)
        if method == "VIDEO_LATENCY":
            return self._ok([], "VIDEO_LATENCY observed", ready=True)
        raise ProtocolError(f"unsupported ready-state RTSP method {method}")

    def _response(self, cseq: int, body: bytes = b"") -> RtspMessage:
        headers = {"CSeq": str(cseq)}
        if body:
            headers["Content-Type"] = "text/parameters"
        if self.session_id and cseq not in {1, 2}:
            headers["Session"] = self.session_id
        return RtspMessage("RTSP/1.0 200 OK", headers, body)

    def _require_request(self, message: RtspMessage, method: str, cseq: int) -> None:
        if not message.start_line.startswith(method + " ") or self._cseq(message) != cseq:
            raise ProtocolError(f"expected {method} CSeq {cseq}")

    def _require_response(self, message: RtspMessage, cseq: int) -> None:
        if message.start_line != "RTSP/1.0 200 OK" or self._cseq(message) != cseq:
            raise ProtocolError(f"expected RTSP 200 CSeq {cseq}")

    @staticmethod
    def _cseq(message: RtspMessage) -> int:
        try:
            return int(message.header("CSeq") or "")
        except ValueError as exc:
            raise ProtocolError("RTSP message omitted numeric CSeq") from exc

    def _ok(self, messages: list[RtspMessage], reason: str, ready: bool = False) -> RtspTransition:
        return RtspTransition(True, [encode_rtsp(item) for item in messages], reason, ready)

    def _stop(self, reason: str) -> RtspTransition:
        self.phase = RtspPhase.STOPPED
        return RtspTransition(False, [], reason)

