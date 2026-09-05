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

    def create_playlist_record(
        self,
        playlist_id: str,
        name: str,
        *,
        description: str | None = None,
        default_order: str = "sequential",
        default_repeat: str = "none",
    ) -> dict[str, Any]:
        now = self._now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO playlists "
                "(id, name, description, default_order, default_repeat, revision, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (playlist_id, name, description, default_order, default_repeat, now, now),
            )
        return self.get_playlist(playlist_id)

    def create_media_asset(self, values: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO media_assets "
                "(id, source_kind, display_name, description, tags_json, original_filename, "
                "content_type, size_bytes, duration_seconds, content_hash, source_value, status, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', ?, ?)",
                (
                    values["id"],
                    values["source_kind"],
                    values["display_name"],
                    values.get("description"),
                    values.get("tags_json", "[]"),
                    values.get("original_filename"),
                    values.get("content_type"),
                    values.get("size_bytes"),
                    values.get("duration_seconds"),
                    values.get("content_hash"),
                    values["source_value"],
                    now,
                    now,
                ),
            )
        return self.get_media_asset(values["id"])

    def get_media_asset(self, asset_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM media_assets WHERE id = ?", (asset_id,)
            ).fetchone()
        )

    def find_media_asset_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM media_assets WHERE content_hash = ?", (content_hash,)
            ).fetchone()
        )

    def update_media_asset(self, asset_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"display_name", "description", "tags_json", "source_value", "status"}
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.get_media_asset(asset_id)
        updates["updated_at"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.transaction() as connection:
            connection.execute(
                f"UPDATE media_assets SET {assignments} WHERE id = ?",
                (*updates.values(), asset_id),
            )
        return self.get_media_asset(asset_id)

    def list_media_assets(
        self,
        *,
        query: str | None = None,
        source_kind: str | None = None,
        status: str | None = None,
        sort: str = "recent_added",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses = ["a.status != 'deleted'"]
        parameters: list[Any] = []
        if query:
            clauses.append(
                "(lower(a.display_name) LIKE ? OR lower(COALESCE(a.description, '')) LIKE ? "
                "OR lower(a.tags_json) LIKE ? OR lower(COALESCE(a.original_filename, '')) LIKE ?)"
            )
            term = f"%{query.strip().lower()}%"
            parameters.extend([term, term, term, term])
        if source_kind:
            clauses.append("a.source_kind = ?")
            parameters.append(source_kind)
        if status:
            clauses.append("a.status = ?")
            parameters.append(status)
        where = " AND ".join(clauses)
        order = {
            "name": "lower(a.display_name), a.id",
            "recent_used": "last_used_at IS NULL, last_used_at DESC, a.id",
            "duration": "a.duration_seconds IS NULL, a.duration_seconds, a.id",
            "recent_added": "a.created_at DESC, a.id",
        }.get(sort, "a.created_at DESC, a.id")
        total = int(
            self._connection.execute(
                f"SELECT count(*) FROM media_assets a WHERE {where}", parameters
            ).fetchone()[0]
        )
        rows = self._connection.execute(
            "SELECT a.*, "
            "(SELECT count(*) FROM playlist_items pi WHERE pi.asset_id = a.id AND pi.removed_at IS NULL) AS reference_count, "
            "(SELECT max(ms.started_at) FROM media_sessions ms WHERE ms.asset_id = a.id) AS last_used_at "
            f"FROM media_assets a WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*parameters, max(1, min(int(limit), 200)), max(0, int(offset))),
        ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def media_asset_references(self, asset_id: str) -> dict[str, int]:
        row = self._connection.execute(
            "SELECT "
            "(SELECT count(*) FROM playlist_items WHERE asset_id = ? AND removed_at IS NULL), "
            "(SELECT count(*) FROM media_sessions WHERE asset_id = ? AND state != 'ended')",
            (asset_id, asset_id),
        ).fetchone()
        return {"playlist_items": int(row[0]), "active_sessions": int(row[1])}

    def mark_media_asset_deleted(self, asset_id: str) -> dict[str, Any] | None:
        now = self._now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE media_assets SET status = 'deleted', source_value = '', "
                "updated_at = ?, deleted_at = ? WHERE id = ? AND status != 'deleted'",
                (now, now, asset_id),
            )
        return self.get_media_asset(asset_id)

    def add_playlist_item_record(
        self, item_id: str, playlist_id: str, asset_id: str, position: int
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO playlist_items "
                "(id, playlist_id, asset_id, position, created_at) VALUES (?, ?, ?, ?, ?)",
                (item_id, playlist_id, asset_id, int(position), self._now()),
            )

    def remove_playlist_item_record(self, item_id: str) -> bool:
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE playlist_items SET removed_at = ? WHERE id = ? AND removed_at IS NULL",
                (self._now(), item_id),
            ).rowcount
        return bool(changed)

    def get_playlist(self, playlist_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
        )

    def list_playlists(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        clause = "" if include_archived else "WHERE archived_at IS NULL"
        rows = self._connection.execute(
            "SELECT p.*, "
            "(SELECT count(*) FROM playlist_items pi WHERE pi.playlist_id = p.id AND pi.removed_at IS NULL) AS item_count, "
            "(SELECT count(*) FROM playback_runs pr WHERE pr.playlist_id = p.id AND pr.state = 'active') AS active_run_count "
            f"FROM playlists p {clause} ORDER BY p.updated_at DESC, p.id"
        ).fetchall()
        return [dict(row) for row in rows]

    def playlist_items(self, playlist_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT pi.*, a.display_name AS asset_display_name, a.source_kind, a.status AS asset_status, "
            "a.content_type, a.size_bytes, a.duration_seconds "
            "FROM playlist_items pi JOIN media_assets a ON a.id = pi.asset_id "
            "WHERE pi.playlist_id = ? AND pi.removed_at IS NULL ORDER BY pi.position, pi.id",
            (playlist_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_playlist_item(self, item_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM playlist_items WHERE id = ?", (item_id,)
            ).fetchone()
        )

    def _require_revision(self, connection, playlist_id: str, expected_revision: int):
        row = connection.execute(
            "SELECT revision FROM playlists WHERE id = ? AND archived_at IS NULL",
            (playlist_id,),
        ).fetchone()
        if row is None:
            return "missing", None
        if int(row[0]) != int(expected_revision):
            return "changed", int(row[0])
        return "ok", int(row[0])

    def update_playlist_record(
        self, playlist_id: str, expected_revision: int, values: dict[str, Any]
    ) -> tuple[str, int | None]:
        allowed = {"name", "description", "default_order", "default_repeat"}
        updates = {key: value for key, value in values.items() if key in allowed}
        with self.transaction() as connection:
            status, revision = self._require_revision(connection, playlist_id, expected_revision)
            if status != "ok":
                return status, revision
            updates["revision"] = revision + 1
            updates["updated_at"] = self._now()
            assignments = ", ".join(f"{key} = ?" for key in updates)
            connection.execute(
                f"UPDATE playlists SET {assignments} WHERE id = ?",
                (*updates.values(), playlist_id),
            )
        return "ok", revision + 1

    def add_playlist_item(
        self,
        item_id: str,
        playlist_id: str,
        asset_id: str,
        title: str | None,
        expected_revision: int,
    ) -> tuple[str, int | None]:
        with self.transaction() as connection:
            status, revision = self._require_revision(connection, playlist_id, expected_revision)
            if status != "ok":
                return status, revision
            position = int(
                connection.execute(
                    "SELECT COALESCE(max(position), -1) + 1 FROM playlist_items "
                    "WHERE playlist_id = ? AND removed_at IS NULL",
                    (playlist_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO playlist_items "
                "(id, playlist_id, asset_id, position, title, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (item_id, playlist_id, asset_id, position, title, self._now()),
            )
            connection.execute(
                "UPDATE playlists SET revision = ?, updated_at = ? WHERE id = ?",
                (revision + 1, self._now(), playlist_id),
            )
        return "ok", revision + 1

    def update_playlist_item(
        self,
        playlist_id: str,
        item_id: str,
        expected_revision: int,
        values: dict[str, Any],
    ) -> tuple[str, int | None]:
        updates = {key: value for key, value in values.items() if key in {"asset_id", "title"}}
        with self.transaction() as connection:
            status, revision = self._require_revision(connection, playlist_id, expected_revision)
            if status != "ok":
                return status, revision
            exists = connection.execute(
                "SELECT 1 FROM playlist_items WHERE id = ? AND playlist_id = ? AND removed_at IS NULL",
                (item_id, playlist_id),
            ).fetchone()
            if exists is None:
                return "item_missing", revision
            assignments = ", ".join(f"{key} = ?" for key in updates)
            if assignments:
                connection.execute(
                    f"UPDATE playlist_items SET {assignments} WHERE id = ?",
                    (*updates.values(), item_id),
                )
            connection.execute(
                "UPDATE playlists SET revision = ?, updated_at = ? WHERE id = ?",
                (revision + 1, self._now(), playlist_id),
            )
        return "ok", revision + 1

    @staticmethod
    def _reposition(connection, playlist_id: str, ordered_ids: list[str]) -> None:
        connection.execute(
            "UPDATE playlist_items SET position = position + 1000000 "
            "WHERE playlist_id = ? AND removed_at IS NULL",
            (playlist_id,),
        )
        for position, item_id in enumerate(ordered_ids):
            connection.execute(
                "UPDATE playlist_items SET position = ? WHERE id = ? AND playlist_id = ? AND removed_at IS NULL",
                (position, item_id, playlist_id),
            )

    def reorder_playlist_items(
        self, playlist_id: str, ordered_ids: list[str], expected_revision: int
    ) -> tuple[str, int | None]:
        with self.transaction() as connection:
            status, revision = self._require_revision(connection, playlist_id, expected_revision)
            if status != "ok":
                return status, revision
            current = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM playlist_items WHERE playlist_id = ? AND removed_at IS NULL ORDER BY position",
                    (playlist_id,),
                )
            ]
            if len(ordered_ids) != len(set(ordered_ids)) or set(current) != set(ordered_ids):
                return "items_changed", revision
            self._reposition(connection, playlist_id, ordered_ids)
            connection.execute(
                "UPDATE playlists SET revision = ?, updated_at = ? WHERE id = ?",
                (revision + 1, self._now(), playlist_id),
            )
        return "ok", revision + 1

    def remove_playlist_item(
        self, playlist_id: str, item_id: str, expected_revision: int
    ) -> tuple[str, int | None]:
        with self.transaction() as connection:
            status, revision = self._require_revision(connection, playlist_id, expected_revision)
            if status != "ok":
                return status, revision
            changed = connection.execute(
                "UPDATE playlist_items SET removed_at = ? "
                "WHERE id = ? AND playlist_id = ? AND removed_at IS NULL",
                (self._now(), item_id, playlist_id),
            ).rowcount
            if not changed:
                return "item_missing", revision
            ordered_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM playlist_items WHERE playlist_id = ? AND removed_at IS NULL ORDER BY position",
                    (playlist_id,),
                )
            ]
            self._reposition(connection, playlist_id, ordered_ids)
            connection.execute(
                "UPDATE playlists SET revision = ?, updated_at = ? WHERE id = ?",
                (revision + 1, self._now(), playlist_id),
            )
        return "ok", revision + 1

    def archive_playlist_record(
        self, playlist_id: str, expected_revision: int
    ) -> tuple[str, int | None]:
        with self.transaction() as connection:
            status, revision = self._require_revision(connection, playlist_id, expected_revision)
            if status != "ok":
                return status, revision
            now = self._now()
            connection.execute(
                "UPDATE playlists SET archived_at = ?, revision = ?, updated_at = ? WHERE id = ?",
                (now, revision + 1, now, playlist_id),
            )
        return "ok", revision + 1

    def active_item_conflicts(
        self, *, playlist_id: str, item_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses = ["pr.playlist_id = ?", "pr.state = 'active'", "ms.state != 'ended'"]
        parameters: list[Any] = [playlist_id]
        if item_id is not None:
            clauses.append("ms.playlist_item_id = ?")
            parameters.append(item_id)
        rows = self._connection.execute(
            "SELECT pr.id AS run_id, pr.target_id, ms.id AS session_id "
            "FROM playback_runs pr JOIN media_sessions ms ON ms.run_id = pr.id "
            f"WHERE {' AND '.join(clauses)} ORDER BY pr.target_id, pr.id",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def run_sessions(self, run_id: str, *, cycle_number: int | None = None) -> list[dict[str, Any]]:
        clause = " AND cycle_number = ?" if cycle_number is not None else ""
        parameters = (run_id, cycle_number) if cycle_number is not None else (run_id,)
        rows = self._connection.execute(
            "SELECT * FROM media_sessions WHERE run_id = ?" + clause + " ORDER BY started_at DESC, id DESC",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def playlist_session_history(
        self, playlist_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT ms.* FROM media_sessions ms "
            "JOIN playback_runs pr ON pr.id = ms.run_id "
            "WHERE pr.playlist_id = ? ORDER BY ms.started_at DESC, ms.id DESC LIMIT ?",
            (playlist_id, max(1, min(int(limit), 200))),
        ).fetchall()
        return [dict(row) for row in rows]

    def playlist_resume_candidates(
        self, playlist_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT ms.* FROM media_sessions ms "
            "JOIN playback_runs pr ON pr.id = ms.run_id "
            "JOIN playlist_items pi ON pi.id = ms.playlist_item_id AND pi.removed_at IS NULL "
            "WHERE pr.playlist_id = ? AND ms.state = 'ended' "
            "AND ms.position_seconds > 0 AND ms.end_reason IN ('stopped', 'preempted', 'failed', 'interrupted') "
            "ORDER BY ms.ended_at DESC, ms.id DESC LIMIT ?",
            (playlist_id, max(1, min(int(limit), 200))),
        ).fetchall()
        return [dict(row) for row in rows]

    def playback_history(
        self, *, target_id: str | None = None, playlist_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses, parameters = [], []
        if target_id:
            clauses.append("ms.target_id = ?")
            parameters.append(target_id)
        if playlist_id:
            clauses.append("pr.playlist_id = ?")
            parameters.append(playlist_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self._connection.execute(
            "SELECT ms.*, pr.playlist_id FROM media_sessions ms "
            "LEFT JOIN playback_runs pr ON pr.id = ms.run_id "
            f"{where} ORDER BY ms.started_at DESC, ms.id DESC LIMIT ?",
            (*parameters, max(1, min(int(limit), 200))),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_run_modes(
        self, run_id: str, *, order_mode: str, repeat_mode: str
    ) -> dict[str, Any] | None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE playback_runs SET order_mode = ?, repeat_mode = ?, updated_at = ? "
                "WHERE id = ? AND state = 'active'",
                (order_mode, repeat_mode, self._now(), run_id),
            )
        return self.get_run(run_id)

    def set_run_cycle(self, run_id: str, cycle_number: int) -> bool:
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE playback_runs SET cycle_number = ?, updated_at = ? WHERE id = ? AND state = 'active'",
                (int(cycle_number), self._now(), run_id),
            ).rowcount
        return bool(changed)

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

    def start_run_with_session(
        self,
        run_id: str,
        session_id: str,
        target_id: str,
        playlist_id: str,
        *,
        order_mode: str,
        repeat_mode: str,
        asset_id: str,
        playlist_item_id: str,
        item_title_snapshot: str | None,
        source_type: str,
        source_label: str | None,
        duration_seconds: float | None,
        seek_supported: bool,
        resumed_from_session_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Atomically replace target ownership and create a run's first session."""
        now = self._now()
        with self.transaction() as connection:
            connection.execute(
                "UPDATE media_sessions SET state = 'ended', end_reason = 'preempted', "
                "updated_at = ?, ended_at = ? WHERE target_id = ? AND state != 'ended'",
                (now, now, target_id),
            )
            connection.execute(
                "UPDATE playback_runs SET state = 'ended', end_reason = 'preempted', "
                "updated_at = ?, ended_at = ? WHERE target_id = ? AND state = 'active'",
                (now, now, target_id),
            )
            connection.execute(
                "INSERT INTO playback_runs "
                "(id, target_id, playlist_id, order_mode, repeat_mode, cycle_number, state, started_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 0, 'active', ?, ?)",
                (run_id, target_id, playlist_id, order_mode, repeat_mode, now, now),
            )
            connection.execute(
                "INSERT INTO media_sessions "
                "(id, run_id, target_id, asset_id, playlist_item_id, item_title_snapshot, "
                "source_type, source_label, cycle_number, state, position_seconds, duration_seconds, "
                "seek_supported, started_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'starting', ?, ?, ?, ?, ?)",
                (session_id, run_id, target_id, asset_id, playlist_item_id,
                 item_title_snapshot, source_type, source_label,
                 0 if resumed_from_session_id is None else None,
                 duration_seconds, int(seek_supported), now, now),
            )
        return self.get_run(run_id), self.get_session(session_id)

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

    def active_runs(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM playback_runs WHERE state = 'active' ORDER BY target_id, id"
        ).fetchall()
        return [dict(row) for row in rows]

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

    def active_session_for_run(self, run_id: str) -> dict[str, Any] | None:
        return self._row(
            self._connection.execute(
                "SELECT * FROM media_sessions WHERE run_id = ? AND state != 'ended'",
                (run_id,),
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

    def update_ended_session_progress(self, session_id: str, position_seconds: float) -> bool:
        position = float(position_seconds)
        if position < 0:
            raise ValueError("INVALID_POSITION")
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE media_sessions SET position_seconds = ?, updated_at = ? "
                "WHERE id = ? AND state = 'ended'",
                (position, self._now(), session_id),
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
            run_id = payload.get("run_id")
            if run_id is None and payload.get("session_id"):
                row = connection.execute(
                    "SELECT run_id FROM media_sessions WHERE id = ?",
                    (payload["session_id"],),
                ).fetchone()
                run_id = row[0] if row else None
            connection.execute(
                "INSERT INTO activity_events "
                "(id, occurred_at, target_id, run_id, session_id, protocol, type, outcome, "
                "summary_key, reason_code, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    payload["id"],
                    payload["occurred_at"],
                    payload["target_id"],
                    run_id,
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
