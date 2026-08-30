"""Bounded, structured and privacy-safe activity event journal."""

from __future__ import annotations

import json
import os
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from miair.runtime.models import ActivityEventSnapshot, EventOutcome, IngressProtocol
from miair.runtime.redaction import redact_event_details


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ActivityEventJournal:
    def __init__(
        self,
        *,
        max_events: int = 500,
        path: str | Path | None = None,
        max_file_bytes: int = 5 * 1024 * 1024,
        backups: int = 3,
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ):
        self._events: deque[ActivityEventSnapshot] = deque(maxlen=max(1, max_events))
        self.path = Path(path) if path is not None else None
        self.max_file_bytes = max_file_bytes
        self.backups = max(0, backups)
        self.clock = clock
        self.id_factory = id_factory
        self.degraded = False

    def append(
        self,
        *,
        target_id: str,
        type: str,
        outcome: EventOutcome,
        summary_key: str,
        protocol: IngressProtocol | None = None,
        session_id: str | None = None,
        reason_code: str | None = None,
        details: dict | None = None,
    ) -> ActivityEventSnapshot:
        event = ActivityEventSnapshot(
            id=self.id_factory(), occurred_at=self.clock(), target_id=target_id,
            session_id=session_id, protocol=protocol, type=type, outcome=outcome,
            summary_key=summary_key, reason_code=reason_code,
            details=redact_event_details(details),
        )
        self._events.append(event)
        self._persist(event)
        return event

    def query(self, *, target_id=None, protocol=None, outcome=None, limit=100):
        result = []
        for event in reversed(self._events):
            if target_id and event.target_id != target_id:
                continue
            if protocol and event.protocol != protocol:
                continue
            if outcome and event.outcome != outcome:
                continue
            result.append(event)
            if len(result) >= max(1, min(int(limit), 500)):
                break
        return result

    def _persist(self, event: ActivityEventSnapshot) -> None:
        if self.path is None:
            return
        payload = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            if self.path.exists() and self.path.stat().st_size + len(payload.encode()) > self.max_file_bytes:
                self._rotate()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(payload)
        except OSError:
            self.degraded = True

    def _rotate(self) -> None:
        if self.backups <= 0:
            self.path.unlink(missing_ok=True)
            return
        for index in range(self.backups, 1, -1):
            older = Path(f"{self.path}.{index - 1}")
            newer = Path(f"{self.path}.{index}")
            if older.exists():
                os.replace(older, newer)
        if self.path.exists():
            os.replace(self.path, Path(f"{self.path}.1"))
