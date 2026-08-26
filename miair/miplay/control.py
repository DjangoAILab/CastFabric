"""Receiver-side state for the observed legacy-clear MiPlay command path."""

from __future__ import annotations

import enum
import hmac
import json
from dataclasses import dataclass

from .protocol import (
    Command,
    CommandFrame,
    OpenDeviceRequest,
    ProtocolError,
    encode_command,
    encode_device_info,
    encode_notify_scalar,
    encode_scalar,
    legacy_challenge_response,
)
from .safety import ModernSafetyReceiver


class ControlPhase(enum.Enum):
    CREATED = "created"
    AWAITING_AUTH = "awaiting_auth"
    READY = "ready"
    OPENED = "opened"
    STOPPED = "stopped"


@dataclass(slots=True)
class ControlResult:
    accepted: bool
    writes: list[bytes]
    reason: str
    open_request: OpenDeviceRequest | None = None


class LegacyReceiverSession:
    """Strict receiver state machine matching the captured LX06 legacy path."""

    def __init__(
        self,
        *,
        challenge: bytes,
        challenge_sequence: int = 0,
        friendly_name: str = "OpenXiaoCast",
        volume: int = 38,
        local_endpoint: tuple[str, int] | None = None,
        peer_endpoint: tuple[str, int] | None = None,
    ):
        if not 12 <= len(challenge) <= 17 or not challenge.isdigit():
            raise ValueError("legacy challenge must be 12 to 17 ASCII digits")
        if not 0 <= volume <= 100:
            raise ValueError("volume out of range")
        self.challenge = bytes(challenge)
        self.challenge_sequence = challenge_sequence
        self.friendly_name = friendly_name
        self.volume = volume
        self.phase = ControlPhase.CREATED
        self.authenticated = False
        self.source_version: str | None = None
        self.source_name: str | None = None
        self.set_play_source_seen = False
        self._media_started = False
        self._notification_sequence = 1
        self._local_endpoint = local_endpoint
        self._peer_endpoint = peer_endpoint
        self.safety: ModernSafetyReceiver | None = None
        self.diagnostics: list[dict[str, int | str | bool]] = []

    def start(self) -> list[bytes]:
        if self.phase is not ControlPhase.CREATED:
            raise RuntimeError("control session already started")
        self.phase = ControlPhase.AWAITING_AUTH
        return [
            encode_command(
                Command.LEGACY_CHALLENGE,
                self.challenge_sequence,
                self.challenge,
            )
        ]

    def process(self, frame: CommandFrame) -> ControlResult:
        self._record(frame)
        if self.phase is ControlPhase.STOPPED:
            return ControlResult(False, [], "control session is stopped")

        if frame.command == Command.SAFETY_INFO:
            return self._start_safety(frame)
        if frame.command in {Command.SAFETY_AUTH, Command.SAFETY_AUTH_ACK}:
            return self._process_safety(frame)
        if frame.command == Command.SAFETY_INFO_ACK:
            return self._stop("unexpected SafetyInfo acknowledgement")

        if frame.command == Command.SOURCE_VERSION:
            return self._source_version(frame)
        if frame.command == Command.LEGACY_CHALLENGE_ACK:
            return self._authenticate(frame)

        if not self.authenticated:
            return self._stop("authentication must complete before business commands")
        if self.phase not in {ControlPhase.READY, ControlPhase.OPENED}:
            return self._stop("business command arrived in an invalid phase")

        if self.safety is not None:
            try:
                decoded = self.safety.process(frame)
            except ProtocolError as exc:
                return self._stop(str(exc))
            assert decoded.plaintext is not None
            frame = decoded.plaintext

        result = self._process_business(frame)
        if result.accepted and self.safety is not None and result.writes:
            try:
                result.writes = self.safety.wrap_writes(result.writes)
            except ProtocolError as exc:
                return self._stop(str(exc))
        return result

    def _process_business(self, frame: CommandFrame) -> ControlResult:

        handlers = {
            Command.GET_DEVICE_INFO: self._get_device_info,
            Command.SET_LOCAL_DEVICE_INFO: self._set_local_device_info,
            Command.SOURCE_CAPABILITY_UPDATE: self._source_capability_update,
            Command.GET_MIRROR_MODE: self._get_mirror_mode,
            Command.GET_VOLUME: self._get_volume,
            Command.GET_STATE: self._get_state,
            Command.GET_MEDIA_INFO: self._get_media_info,
            Command.HEARTBEAT: self._heartbeat,
            Command.SET_PLAY_SOURCE: self._set_play_source,
            Command.OPEN: self._open,
            Command.SET_MEDIA_INFO: self._set_media_info,
            Command.PAUSE: self._pause,
            Command.RESUME: self._resume,
            Command.CLOSE: self._close,
        }
        try:
            handler = handlers.get(Command(frame.command))
        except ValueError:
            handler = None
        if handler is None:
            return self._stop(f"unsupported legacy command 0x{frame.command:04x}")
        return handler(frame)

    def media_started(self) -> list[bytes]:
        if self.phase is not ControlPhase.OPENED or self._media_started:
            return []
        self._media_started = True
        first = self._notify("first-audiopcm", 1)
        state = self._notify("state", 2)
        writes = [first, state]
        if self.safety is not None:
            return self.safety.wrap_writes(writes)
        return writes

    def safety_diagnostics(self) -> dict[str, str | bool | None] | None:
        return self.safety.diagnostics() if self.safety is not None else None

    def _start_safety(self, frame: CommandFrame) -> ControlResult:
        if not self.authenticated:
            return self._stop("SafetyInfo arrived before legacy authentication")
        if self.safety is not None:
            return self._stop("duplicate SafetyInfo offer")
        if self._local_endpoint is None or self._peer_endpoint is None:
            return self._stop("modern Safety protocol requires TCP endpoint context")
        try:
            self.safety = ModernSafetyReceiver(self._local_endpoint, self._peer_endpoint)
            result = self.safety.accept_info(frame)
        except ProtocolError as exc:
            return self._stop(str(exc))
        return self._ok(result.writes, "SafetyInfo negotiated")

    def _process_safety(self, frame: CommandFrame) -> ControlResult:
        if self.safety is None:
            return self._stop("SafetyAuth arrived before SafetyInfo")
        try:
            result = self.safety.process(frame)
        except ProtocolError as exc:
            return self._stop(str(exc))
        return self._ok(result.writes, self.safety.phase)

    def _source_version(self, frame: CommandFrame) -> ControlResult:
        if self.source_version is not None:
            return self._stop("duplicate source version")
        if not frame.payload.endswith(b"\0"):
            return self._stop("source version is not NUL terminated")
        try:
            self.source_version = frame.payload[:-1].decode("ascii")
        except UnicodeDecodeError:
            return self._stop("source version is not ASCII")
        return self._ok(
            [encode_command(Command.SOURCE_VERSION_ACK, frame.sequence, b"2.1.5091615\0")],
            "source version acknowledged",
        )

    def _authenticate(self, frame: CommandFrame) -> ControlResult:
        if self.authenticated:
            return self._stop("duplicate legacy authentication")
        expected = legacy_challenge_response(self.challenge)
        if frame.sequence != self.challenge_sequence or not hmac.compare_digest(
            frame.payload, expected
        ):
            return self._stop("legacy authentication failed")
        self.authenticated = True
        self.phase = ControlPhase.READY
        return self._ok([], "legacy authentication verified")

    def _get_device_info(self, frame: CommandFrame) -> ControlResult:
        if frame.payload:
            return self._stop("getDeviceInfo payload must be empty")
        payload = encode_device_info(
            {
                "name": self.friendly_name,
                "model": "openxiaocast.gateway",
                "support": "audio",
                "mirrorMode": "2",
            }
        )
        return self._ack(Command.GET_DEVICE_INFO_ACK, frame.sequence, payload)

    def _set_local_device_info(self, frame: CommandFrame) -> ControlResult:
        try:
            payload = json.loads(frame.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._stop("setLocalDeviceInfo payload is not JSON")
        if not isinstance(payload, dict):
            return self._stop("setLocalDeviceInfo payload is not an object")
        source_name = payload.get("sourceName")
        if isinstance(source_name, str) and source_name:
            self.source_name = source_name[:120]
        return self._ack(Command.SET_LOCAL_DEVICE_INFO_ACK, frame.sequence)

    def _source_capability_update(self, frame: CommandFrame) -> ControlResult:
        """Accept the post-auth capability update observed from current MIUI.

        The K60 source does not wait for an acknowledgement, so this remains a
        receive-only compatibility boundary until a 0x0417 wire response is
        observed from an official receiver.
        """
        return self._ok([], "source capability update observed")

    def _get_mirror_mode(self, frame: CommandFrame) -> ControlResult:
        return self._empty_query_ack(frame, Command.GET_MIRROR_MODE_ACK, encode_scalar(2))

    def _get_volume(self, frame: CommandFrame) -> ControlResult:
        return self._empty_query_ack(frame, Command.GET_VOLUME_ACK, encode_scalar(self.volume))

    def _get_state(self, frame: CommandFrame) -> ControlResult:
        state = 2 if self._media_started else 3
        return self._empty_query_ack(frame, Command.GET_STATE_ACK, encode_scalar(state))

    def _get_media_info(self, frame: CommandFrame) -> ControlResult:
        return self._empty_query_ack(frame, Command.GET_MEDIA_INFO_ACK, b"")

    def _heartbeat(self, frame: CommandFrame) -> ControlResult:
        return self._empty_query_ack(frame, Command.HEARTBEAT_ACK, b"")

    def _set_play_source(self, frame: CommandFrame) -> ControlResult:
        try:
            parsed = json.loads(frame.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._stop("setPlaySource payload is not JSON")
        if not isinstance(parsed, dict):
            return self._stop("setPlaySource payload is not an object")
        self.set_play_source_seen = True
        # The captured source does not wait for 0x0041 and may already send Open.
        return self._ok([], "play source observed")

    def _open(self, frame: CommandFrame) -> ControlResult:
        if not self.set_play_source_seen and self.safety is None:
            return self._stop("Open arrived before setPlaySource")
        try:
            request = OpenDeviceRequest.parse(
                frame.payload,
                allow_missing_nul=self.safety is not None,
            )
        except ProtocolError as exc:
            return self._stop(str(exc))
        self.phase = ControlPhase.OPENED
        return ControlResult(True, [], "WFD source endpoint accepted", request)

    def _set_media_info(self, frame: CommandFrame) -> ControlResult:
        try:
            value = json.loads(frame.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._stop("setMediaInfo payload is not JSON")
        if not isinstance(value, dict):
            return self._stop("setMediaInfo payload is not an object")
        return self._ack(Command.SET_MEDIA_INFO_ACK, frame.sequence)

    def _pause(self, frame: CommandFrame) -> ControlResult:
        return self._ack(Command.PAUSE_ACK, frame.sequence)

    def _resume(self, frame: CommandFrame) -> ControlResult:
        return self._ack(Command.RESUME_ACK, frame.sequence)

    def _close(self, frame: CommandFrame) -> ControlResult:
        self.phase = ControlPhase.STOPPED
        return self._ok([], "source closed the session")

    def _empty_query_ack(
        self, frame: CommandFrame, command: Command, payload: bytes
    ) -> ControlResult:
        if frame.payload:
            return self._stop(f"command 0x{frame.command:04x} payload must be empty")
        return self._ack(command, frame.sequence, payload)

    def _ack(
        self, command: Command, sequence: int, payload: bytes = b""
    ) -> ControlResult:
        return self._ok([encode_command(command, sequence, payload)], "acknowledged")

    def _notify(self, label: str, value: int) -> bytes:
        sequence = self._notification_sequence
        self._notification_sequence = (sequence + 1) & 0xFFFF
        return encode_command(
            Command.NOTIFY, sequence, encode_notify_scalar(label, value)
        )

    def _ok(self, writes: list[bytes], reason: str) -> ControlResult:
        return ControlResult(True, writes, reason)

    def _stop(self, reason: str) -> ControlResult:
        self.phase = ControlPhase.STOPPED
        return ControlResult(False, [], reason)

    def _record(self, frame: CommandFrame) -> None:
        self.diagnostics.append(
            {
                "command": f"0x{frame.command:04x}",
                "sequence": frame.sequence,
                "payload_bytes": len(frame.payload),
                "authenticated": self.authenticated,
            }
        )
        if len(self.diagnostics) > 64:
            del self.diagnostics[:-64]
