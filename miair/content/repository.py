"""Single SQLite boundary for persistent CastFabric content state."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


SCHEMA_VERSION = 1


class ContentStorageError(RuntimeError):
    """Stable wrapper for storage failures at the application boundary."""

    code = "STORAGE_ERROR"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


MIGRATIONS = (
    """
    CREATE TABLE media_assets (
        id TEXT PRIMARY KEY,
        source_kind TEXT NOT NULL CHECK (source_kind IN ('managed_file', 'external_url')),
        display_name TEXT NOT NULL,
        description TEXT,
        tags_json TEXT NOT NULL DEFAULT '[]',
        original_filename TEXT,
        content_type TEXT,
        size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
        duration_seconds REAL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
        content_hash TEXT,
        source_value TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available', 'unavailable', 'deleted')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deleted_at TEXT,
        UNIQUE (content_hash)
    );

    CREATE TABLE playlists (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        default_order TEXT NOT NULL DEFAULT 'sequential' CHECK (default_order IN ('sequential', 'random')),
        default_repeat TEXT NOT NULL DEFAULT 'none' CHECK (default_repeat IN ('none', 'all')),
        revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        archived_at TEXT
    );

    CREATE TABLE playlist_items (
        id TEXT PRIMARY KEY,
        playlist_id TEXT NOT NULL REFERENCES playlists(id),
        asset_id TEXT NOT NULL REFERENCES media_assets(id),
        position INTEGER NOT NULL CHECK (position >= 0),
        title TEXT,
        created_at TEXT NOT NULL,
        removed_at TEXT
    );

    CREATE TABLE playback_runs (
        id TEXT PRIMARY KEY,
        target_id TEXT NOT NULL,
        playlist_id TEXT NOT NULL REFERENCES playlists(id),
        order_mode TEXT NOT NULL CHECK (order_mode IN ('sequential', 'random')),
        repeat_mode TEXT NOT NULL CHECK (repeat_mode IN ('none', 'all')),
        cycle_number INTEGER NOT NULL DEFAULT 0 CHECK (cycle_number >= 0),
        state TEXT NOT NULL CHECK (state IN ('active', 'ended')),
        end_reason TEXT CHECK (end_reason IN ('completed', 'stopped', 'preempted', 'failed', 'interrupted')),
        started_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        ended_at TEXT
    );

    CREATE TABLE media_sessions (
        id TEXT PRIMARY KEY,
        run_id TEXT REFERENCES playback_runs(id),
        target_id TEXT NOT NULL,
        asset_id TEXT REFERENCES media_assets(id),
        playlist_item_id TEXT REFERENCES playlist_items(id),
        item_title_snapshot TEXT,
        source_type TEXT NOT NULL,
        source_label TEXT,
        cycle_number INTEGER CHECK (cycle_number IS NULL OR cycle_number >= 0),
        state TEXT NOT NULL CHECK (state IN ('starting', 'playing', 'paused', 'ended')),
        position_seconds REAL CHECK (position_seconds IS NULL OR position_seconds >= 0),
        duration_seconds REAL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
        seek_supported INTEGER NOT NULL DEFAULT 0 CHECK (seek_supported IN (0, 1)),
        started_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        ended_at TEXT,
        end_reason TEXT CHECK (end_reason IN ('completed', 'stopped', 'skipped', 'failed', 'preempted', 'interrupted')),
        error_code TEXT
    );

    CREATE TABLE activity_events (
        id TEXT PRIMARY KEY,
        occurred_at TEXT NOT NULL,
        target_id TEXT NOT NULL,
        run_id TEXT REFERENCES playback_runs(id),
        session_id TEXT REFERENCES media_sessions(id),
        protocol TEXT,
        type TEXT NOT NULL,
        outcome TEXT NOT NULL,
        summary_key TEXT NOT NULL,
        reason_code TEXT,
        details_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE UNIQUE INDEX active_run_per_target
        ON playback_runs(target_id) WHERE state = 'active';
    CREATE UNIQUE INDEX active_session_per_target
        ON media_sessions(target_id) WHERE state != 'ended';
    CREATE UNIQUE INDEX active_session_per_run
        ON media_sessions(run_id) WHERE run_id IS NOT NULL AND state != 'ended';
    CREATE UNIQUE INDEX active_item_position
        ON playlist_items(playlist_id, position) WHERE removed_at IS NULL;
    CREATE INDEX media_assets_lookup ON media_assets(status, source_kind, updated_at);
    CREATE INDEX playlist_items_lookup ON playlist_items(playlist_id, removed_at, position);
    CREATE INDEX sessions_history ON media_sessions(target_id, started_at DESC);
    CREATE INDEX events_history ON activity_events(occurred_at DESC);
    """,
)


class ContentRepository:
    """Own one SQLite connection and serialize every business transaction."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] = _utcnow,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    @property
    def schema_version(self) -> int:
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    @property
    def journal_mode(self) -> str:
        return str(self._connection.execute("PRAGMA journal_mode").fetchone()[0])

    def business_tables(self) -> set[str]:
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        return {str(row[0]) for row in rows}

    def _migrate(self) -> None:
        version = self.schema_version
        if version > SCHEMA_VERSION:
            self._connection.close()
            raise RuntimeError("UNSUPPORTED_SCHEMA_VERSION")
        for target_version in range(version + 1, SCHEMA_VERSION + 1):
            script = MIGRATIONS[target_version - 1]
            try:
                with self._lock:
                    self._connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + script
                        + f"\nPRAGMA user_version = {target_version};\nCOMMIT;"
                    )
            except sqlite3.Error as exc:
                try:
                    self._connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise ContentStorageError("SCHEMA_MIGRATION_FAILED") from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield self._connection
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise

    def _now(self) -> str:
        return self.clock().isoformat()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def create_playlist_record(self, playlist_id: str, name: str) -> dict[str, Any]:
        now = self._now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO playlists "
                "(id, name, default_order, default_repeat, revision, created_at, updated_at) "
                "VALUES (?, ?, 'sequential', 'none', 1, ?, ?)",
                (playlist_id, name, now, now),
            )
        return self.get_playlist(playlist_id)

    def get_playlist(self, playlist_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
        )

    def create_run(
        self,
        run_id: str,
        target_id: str,
        playlist_id: str,
        *,
        order_mode: str = "sequential",
        repeat_mode: str = "none",
        cycle_number: int = 0,
    ) -> dict[str, Any]:
        now = self._now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO playback_runs "
                "(id, target_id, playlist_id, order_mode, repeat_mode, cycle_number, state, started_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (
                    run_id,
                    target_id,
                    playlist_id,
                    order_mode,
                    repeat_mode,
                    cycle_number,
                    now,
                    now,
                ),
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM playback_runs WHERE id = ?", (run_id,)
            ).fetchone()
        )

    def active_run(self, target_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM playback_runs WHERE target_id = ? AND state = 'active'",
                (target_id,),
            ).fetchone()
        )

    def end_run(self, run_id: str, reason: str) -> bool:
        now = self._now()
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE playback_runs SET state = 'ended', end_reason = ?, updated_at = ?, ended_at = ? "
                "WHERE id = ? AND state = 'active'",
                (reason, now, now, run_id),
            ).rowcount
        return bool(changed)

    def create_session(
        self,
        session_id: str,
        target_id: str,
        *,
        source_type: str,
        run_id: str | None = None,
        asset_id: str | None = None,
        playlist_item_id: str | None = None,
        item_title_snapshot: str | None = None,
        source_label: str | None = None,
        cycle_number: int | None = None,
        duration_seconds: float | None = None,
        seek_supported: bool = False,
    ) -> dict[str, Any]:
        now = self._now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO media_sessions "
                "(id, run_id, target_id, asset_id, playlist_item_id, item_title_snapshot, "
                "source_type, source_label, cycle_number, state, duration_seconds, seek_supported, "
                "started_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'starting', ?, ?, ?, ?)",
                (
                    session_id,
                    run_id,
                    target_id,
                    asset_id,
                    playlist_item_id,
                    item_title_snapshot,
                    source_type,
                    source_label,
                    cycle_number,
                    duration_seconds,
                    int(seek_supported),
                    now,
                    now,
                ),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM media_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        )

    def active_session(self, target_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM media_sessions WHERE target_id = ? AND state != 'ended'",
                (target_id,),
            ).fetchone()
        )

    def transition_session(self, session_id: str, state: str) -> bool:
        if state not in {"starting", "playing", "paused"}:
            raise ValueError("INVALID_SESSION_STATE")
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE media_sessions SET state = ?, updated_at = ? "
                "WHERE id = ? AND state != 'ended'",
                (state, self._now(), session_id),
            ).rowcount
        return bool(changed)

    def update_session_progress(
        self,
        session_id: str,
        position_seconds: float,
        *,
        duration_seconds: float | None = None,
    ) -> bool:
        position = float(position_seconds)
        if position < 0:
            raise ValueError("INVALID_POSITION")
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE media_sessions SET position_seconds = ?, "
                "duration_seconds = COALESCE(?, duration_seconds), updated_at = ? "
                "WHERE id = ? AND state != 'ended'",
                (position, duration_seconds, self._now(), session_id),
            ).rowcount
        return bool(changed)

    def end_session(
        self,
        session_id: str,
        reason: str,
        *,
        error_code: str | None = None,
        position_seconds: float | None = None,
    ) -> bool:
        now = self._now()
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE media_sessions SET state = 'ended', end_reason = ?, error_code = ?, "
                "position_seconds = COALESCE(?, position_seconds), updated_at = ?, ended_at = ? "
                "WHERE id = ? AND state != 'ended'",
                (reason, error_code, position_seconds, now, now, session_id),
            ).rowcount
        return bool(changed)

    def interrupt_active_playback(self) -> dict[str, int]:
        now = self._now()
        with self.transaction() as connection:
            sessions = connection.execute(
                "UPDATE media_sessions SET state = 'ended', end_reason = 'interrupted', "
                "updated_at = ?, ended_at = ? WHERE state != 'ended'",
                (now, now),
            ).rowcount
            runs = connection.execute(
                "UPDATE playback_runs SET state = 'ended', end_reason = 'interrupted', "
                "updated_at = ?, ended_at = ? WHERE state = 'active'",
                (now, now),
            ).rowcount
        return {"runs": runs, "sessions": sessions}

    def append_event(self, payload: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO activity_events "
                "(id, occurred_at, target_id, run_id, session_id, protocol, type, outcome, "
                "summary_key, reason_code, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload["id"],
                    payload["occurred_at"],
                    payload["target_id"],
                    payload.get("run_id"),
                    payload.get("session_id"),
                    payload.get("protocol"),
                    payload["type"],
                    payload["outcome"],
                    payload["summary_key"],
                    payload.get("reason_code"),
                    json.dumps(payload.get("details") or {}, ensure_ascii=False),
                ),
            )

    def query_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM activity_events ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json") or "{}")
            result.append(item)
        return result

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True
