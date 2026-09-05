"""Per-output media-session ownership and stale callback protection."""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from miair.runtime.events import ActivityEventJournal
from miair.runtime.models import (
    EventOutcome, IngressProtocol, MediaSessionSnapshot,
    SessionSourceSnapshot, SessionState,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaSessionCoordinator:
    def __init__(self, *, journal: ActivityEventJournal | None = None,
                 clock: Callable[[], datetime] = _utcnow,
                 id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
                 repository=None):
        self.journal = journal
        self.clock = clock
        self.id_factory = id_factory
        self.repository = repository
        self._current: dict[str, MediaSessionSnapshot] = {}
        self._session_targets: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._recent: deque[MediaSessionSnapshot] = deque(maxlen=200)

    def current(self, target_id: str) -> MediaSessionSnapshot | None:
        return self._current.get(target_id)

    def current_all(self) -> tuple[MediaSessionSnapshot, ...]:
        return tuple(self._current[key] for key in sorted(self._current))

    def query(self, *, include_recent: bool = False, limit: int = 100):
        current = list(self.current_all())
        if include_recent:
            current.extend(reversed(self._recent))
        return current[: max(1, min(int(limit), 200))]

    async def begin(self, target_id: str, protocol: IngressProtocol, *,
                    source: SessionSourceSnapshot | None = None,
                    media_format: str | None = None,
                    session_id: str | None = None,
                    persist: bool = True,
                    session_context: dict | None = None) -> MediaSessionSnapshot:
        async with self._locks.setdefault(target_id, asyncio.Lock()):
            old = self._current.get(target_id)
            if old and self.journal:
                self.journal.append(target_id=target_id, session_id=old.id,
                    protocol=old.protocol, type="session.preempted",
                    outcome=EventOutcome.INFO, summary_key="activity.session_preempted")
            if old:
                if self.repository is not None:
                    self.repository.end_session(old.id, "preempted")
                self._session_targets.pop(old.id, None)
                self._recent.append(
                    replace(old, state=SessionState.STOPPED, ended_at=self.clock())
                )
            session = MediaSessionSnapshot(
                id=session_id or self.id_factory(), target_id=target_id, protocol=protocol,
                state=SessionState.STARTING,
                source=source or SessionSourceSnapshot(),
                media_format=media_format, started_at=self.clock(),
            )
            self._current[target_id] = session
            self._session_targets[session.id] = target_id
            if self.repository is not None and persist:
                context = session_context or {}
                self.repository.create_session(
                    session.id,
                    target_id,
                    source_type=context.get("source_type", protocol.value),
                    source_label=context.get("source_label", session.source.device_name),
                    run_id=context.get("run_id"),
                    asset_id=context.get("asset_id"),
                    playlist_item_id=context.get("playlist_item_id"),
                    item_title_snapshot=context.get("item_title_snapshot"),
                    cycle_number=context.get("cycle_number"),
                    duration_seconds=context.get("duration_seconds"),
                    seek_supported=context.get("seek_supported", False),
                )
            if self.journal:
                self.journal.append(target_id=target_id, session_id=session.id,
                    protocol=protocol, type="session.started",
                    outcome=EventOutcome.SUCCESS, summary_key="activity.session_started",
                    details={"media_format": media_format} if media_format else None)
            return session

    async def transition(self, session_id: str, state: SessionState) -> bool:
        target_id = self._session_targets.get(session_id)
        if not target_id:
            return False
        async with self._locks.setdefault(target_id, asyncio.Lock()):
            current = self._current.get(target_id)
            if current is None or current.id != session_id:
                return False
            self._current[target_id] = replace(current, state=state)
            if self.repository is not None:
                self.repository.transition_session(session_id, state.value)
            return True

    async def end(
        self,
        session_id: str,
        *,
        failed: bool = False,
        reason: str | None = None,
    ) -> bool:
        target_id = self._session_targets.get(session_id)
        if not target_id:
            return False
        async with self._locks.setdefault(target_id, asyncio.Lock()):
            current = self._current.get(target_id)
            if current is None or current.id != session_id:
                return False
            del self._current[target_id]
            self._session_targets.pop(session_id, None)
            self._recent.append(
                replace(
                    current,
                    state=SessionState.FAILED if failed else SessionState.STOPPED,
                    ended_at=self.clock(),
                )
            )
            if self.repository is not None:
                self.repository.end_session(
                    session_id,
                    reason or ("failed" if failed else "stopped"),
                )
            if self.journal:
                self.journal.append(target_id=target_id, session_id=session_id,
                    protocol=current.protocol,
                    type="session.failed" if failed else "session.ended",
                    outcome=EventOutcome.FAILED if failed else EventOutcome.SUCCESS,
                    summary_key="activity.session_failed" if failed else "activity.session_ended")
            return True
