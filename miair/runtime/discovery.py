"""Atomic lifecycle and observations for local output-target discovery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Awaitable, Callable

from miair.dlna.client import DiscoveredDLNATarget
from miair.targets import normalize_target_id


class DiscoveryState(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    READY = "ready"
    ERROR = "error"


class DiscoveryBusyError(RuntimeError):
    pass


@dataclass(frozen=True)
class TargetObservation:
    id: str
    name: str
    location: str
    services: dict[str, str]
    observed_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TargetDiscoveryRegistry:
    """Keep the last complete discovery snapshot while a new scan runs."""

    def __init__(
        self,
        discover: Callable[[], Awaitable[list[DiscoveredDLNATarget]]],
        *,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self._discover = discover
        self._clock = clock
        self._observations: dict[str, TargetObservation] = {}
        self._scan_task: asyncio.Task | None = None
        self.state = DiscoveryState.IDLE
        self.observed_at: datetime | None = None
        self.last_attempt_at: datetime | None = None
        self.error_code: str | None = None

    async def scan(self) -> dict[str, TargetObservation]:
        current = asyncio.current_task()
        if self._scan_task is not None and not self._scan_task.done():
            raise DiscoveryBusyError("target discovery is already running")
        self._scan_task = current
        self.state = DiscoveryState.SCANNING
        self.error_code = None
        self.last_attempt_at = self._clock()
        try:
            discovered = await self._discover()
            completed_at = self._clock()
            replacement = {}
            for item in discovered:
                target_id = normalize_target_id(item.id)
                if not target_id:
                    continue
                replacement[target_id] = TargetObservation(
                    id=target_id,
                    name=str(item.name or target_id),
                    location=str(item.location or ""),
                    services=dict(item.services),
                    observed_at=completed_at,
                )
            self._observations = replacement
            self.observed_at = completed_at
            self.state = DiscoveryState.READY
            return self.snapshot()
        except Exception as exc:
            self.state = DiscoveryState.ERROR
            self.error_code = self._error_code(exc)
            raise
        finally:
            if self._scan_task is current:
                self._scan_task = None

    def snapshot(self) -> dict[str, TargetObservation]:
        return dict(self._observations)

    def status(self) -> dict[str, str | None]:
        return {
            "state": self.state.value,
            "observed_at": self.observed_at.isoformat()
            if self.observed_at
            else None,
            "last_attempt_at": self.last_attempt_at.isoformat()
            if self.last_attempt_at
            else None,
            "error_code": self.error_code,
        }

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return "SCAN_TIMEOUT"
        if isinstance(exc, OSError):
            return "SCAN_IO_ERROR"
        return "SCAN_FAILED"
