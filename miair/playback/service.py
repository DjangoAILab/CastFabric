"""One application boundary for console, HTTP, MCP, and future ingresses."""

from __future__ import annotations

from typing import Any

from miair.runtime.models import IngressProtocol, SessionState
from miair.targets import normalize_target_id


class PlaybackServiceError(RuntimeError):
    """Stable business failure safe to project through public adapters."""

    def __init__(self, code: str, target_id: str):
        super().__init__(code)
        self.code = code
        self.target_id = target_id


class PlaybackService:
    def __init__(self, suite_registry, session_coordinator):
        self.suite_registry = suite_registry
        self.session_coordinator = session_coordinator

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
    ) -> dict[str, Any]:
        normalized, suite = self._suite_for(target_id)
        session = await self.session_coordinator.begin(
            normalized,
            IngressProtocol.MCP,
            media_format=media_format,
        )
        suite.current_session_id = session.id
        try:
            accepted = await suite.controller.play_url(url, play_type=2)
            if not accepted:
                raise PlaybackServiceError("TARGET_COMMAND_FAILED", normalized)
        except Exception as exc:
            await self.session_coordinator.end(session.id, failed=True)
            suite.current_session_id = None
            if isinstance(exc, PlaybackServiceError):
                raise
            raise PlaybackServiceError("TARGET_COMMAND_FAILED", normalized) from exc
        await self.session_coordinator.transition(session.id, SessionState.PLAYING)
        return {
            "ok": True,
            "target_id": normalized,
            "session_id": session.id,
            "state": SessionState.PLAYING.value,
        }

    async def pause(self, target_id: str) -> dict[str, Any]:
        normalized, suite = await self._command(target_id, "pause")
        session = self.session_coordinator.current(normalized)
        if session is not None and session.protocol is IngressProtocol.MCP:
            await self.session_coordinator.transition(session.id, SessionState.PAUSED)
        return {"ok": True, "target_id": normalized, "state": "paused"}

    async def stop(self, target_id: str) -> dict[str, Any]:
        normalized, suite = await self._command(target_id, "stop")
        session = self.session_coordinator.current(normalized)
        if session is not None and session.protocol is IngressProtocol.MCP:
            await self.session_coordinator.end(session.id)
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
        return {
            "ok": True,
            "target_id": normalized,
            "volume": normalized_volume,
        }

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
        return {
            "ok": True,
            "target_id": normalized,
            "state": state,
            "volume": raw.get("volume"),
        }
