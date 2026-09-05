"""One application boundary for console, HTTP, MCP, and future ingresses."""

from __future__ import annotations

import math
from typing import Any

from miair.runtime.models import IngressProtocol, SessionState
from miair.targets import normalize_target_id


class PlaybackServiceError(RuntimeError):
    """Stable business failure safe to project through public adapters."""

    def __init__(self, code: str, target_id: str):
        super().__init__(code)
        self.code = code
        self.target_id = target_id


def normalize_position_seconds(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlaybackServiceError("INVALID_POSITION", "")
    if not math.isfinite(value) or value < 0 or int(value) != value:
        raise PlaybackServiceError("INVALID_POSITION", "")
    return int(value)


class PlaybackService:
    def __init__(self, suite_registry, session_coordinator, *, before_play=None):
        self.suite_registry = suite_registry
        self.session_coordinator = session_coordinator
        self.before_play = before_play

    def _suite_for(self, target_id: str):
        normalized = normalize_target_id(target_id)
        suite = self.suite_registry.get(normalized)
        if suite is None:
            raise PlaybackServiceError("TARGET_NOT_FOUND", normalized)
        if not suite.target.enabled:
            raise PlaybackServiceError("TARGET_DISABLED", normalized)
        return normalized, suite

    def controller_for(self, target_id: str):
        _normalized, suite = self._suite_for(target_id)
        return suite.controller

    async def _command(self, target_id: str, method: str, *args, **kwargs):
        normalized, suite = self._suite_for(target_id)
        try:
            accepted = await getattr(suite.controller, method)(*args, **kwargs)
        except Exception as exc:
            raise PlaybackServiceError("TARGET_COMMAND_FAILED", normalized) from exc
        if not accepted:
            raise PlaybackServiceError("TARGET_COMMAND_FAILED", normalized)
        return normalized, suite

    async def play_url(
        self,
        target_id: str,
        url: str,
        *,
        media_format: str | None = None,
        start_position_seconds: int = 0,
        preempt: bool = True,
        session_id: str | None = None,
        persist_session: bool = True,
        session_context: dict | None = None,
    ) -> dict[str, Any]:
        position = normalize_position_seconds(start_position_seconds)
        normalized, suite = self._suite_for(target_id)
        if preempt and self.before_play is not None:
            await self.before_play(normalized)
        session = await self.session_coordinator.begin(
            normalized,
            IngressProtocol.MCP,
            media_format=media_format,
            session_id=session_id,
            persist=persist_session,
            session_context=session_context,
        )
        suite.current_session_id = session.id
        output_started = False
        try:
            accepted = await suite.controller.play_url(url, play_type=2)
            if not accepted:
                raise PlaybackServiceError("TARGET_COMMAND_FAILED", normalized)
            output_started = True
            if position and not await suite.controller.seek(position):
                raise PlaybackServiceError("SEEK_UNSUPPORTED", normalized)
        except Exception as exc:
            if output_started:
                try:
                    await suite.controller.stop()
                except Exception:
                    pass
            await self.session_coordinator.end(
                session.id, failed=True,
                error_code=getattr(exc, "code", "TARGET_COMMAND_FAILED"),
            )
            suite.current_session_id = None
            if isinstance(exc, PlaybackServiceError):
                raise
            raise PlaybackServiceError("TARGET_COMMAND_FAILED", normalized) from exc
        await self.session_coordinator.transition(session.id, SessionState.PLAYING)
        result = {
            "ok": True,
            "target_id": normalized,
            "session_id": session.id,
            "state": SessionState.PLAYING.value,
        }
        if position:
            result["position_seconds"] = position
        return result

    async def seek(
        self,
        target_id: str,
        position_seconds: int,
        *,
        if_session_id: str | None = None,
    ) -> dict[str, Any]:
        position = normalize_position_seconds(position_seconds)
        normalized, suite = self._suite_for(target_id)
        session = self.session_coordinator.current(normalized)
        if if_session_id is not None and (
            session is None or session.id != if_session_id
        ):
            raise PlaybackServiceError("SESSION_CHANGED", normalized)
        try:
            accepted = await suite.controller.seek(position)
        except Exception as exc:
            raise PlaybackServiceError("TARGET_COMMAND_FAILED", normalized) from exc
        if not accepted:
            raise PlaybackServiceError("SEEK_UNSUPPORTED", normalized)
        return {
            "ok": True,
            "target_id": normalized,
            "session_id": session.id if session else None,
            "position_seconds": position,
            "state": session.state.value if session else "unknown",
        }

    async def pause(self, target_id: str) -> dict[str, Any]:
        normalized, suite = await self._command(target_id, "pause")
        session = self.session_coordinator.current(normalized)
        if session is not None and session.protocol is IngressProtocol.MCP:
            await self.session_coordinator.transition(session.id, SessionState.PAUSED)
        return {"ok": True, "target_id": normalized, "state": "paused"}

    async def resume(self, target_id: str) -> dict[str, Any]:
        normalized, _suite = await self._command(target_id, "resume")
        session = self.session_coordinator.current(normalized)
        if session is not None and session.protocol is IngressProtocol.MCP:
            await self.session_coordinator.transition(session.id, SessionState.PLAYING)
        return {"ok": True, "target_id": normalized, "state": "playing"}

    async def stop(self, target_id: str, *, reason: str = "stopped") -> dict[str, Any]:
        normalized, suite = await self._command(target_id, "stop")
        session = self.session_coordinator.current(normalized)
        if session is not None and session.protocol is IngressProtocol.MCP:
            await self.session_coordinator.end(session.id, reason=reason)
            if suite.current_session_id == session.id:
                suite.current_session_id = None
        return {"ok": True, "target_id": normalized, "state": "stopped"}

    async def set_volume(self, target_id: str, volume: int) -> dict[str, Any]:
        normalized_volume = max(0, min(100, int(volume)))
        normalized, _suite = await self._command(
            target_id,
            "set_volume",
            normalized_volume,
        )
        result = {
            "ok": True,
            "target_id": normalized,
            "volume": normalized_volume,
        }
        return result

    async def get_status(self, target_id: str) -> dict[str, Any]:
        normalized, suite = self._suite_for(target_id)
        try:
            raw = dict(await suite.controller.get_status())
        except Exception as exc:
            raise PlaybackServiceError("TARGET_COMMAND_FAILED", normalized) from exc
        raw_state = raw.get("state")
        if isinstance(raw_state, str):
            state = raw_state.strip().lower()
        else:
            state = {1: "playing", 2: "paused"}.get(raw.get("status"), "stopped")
        result = {
            "ok": True,
            "target_id": normalized,
            "state": state,
            "volume": raw.get("volume"),
        }
        for key in ("position_seconds", "duration_seconds", "seek_supported"):
            if key in raw:
                result[key] = raw[key]
        return result
