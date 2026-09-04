import sqlite3
from datetime import datetime, timezone

import pytest

from miair.content.repository import ContentRepository, SCHEMA_VERSION


NOW = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
BUSINESS_TABLES = {
    "media_assets",
    "playlists",
    "playlist_items",
    "playback_runs",
    "media_sessions",
    "activity_events",
}


def _repository(tmp_path):
    return ContentRepository(tmp_path / "castfabric.sqlite3", clock=lambda: NOW)


def test_cold_start_creates_only_six_business_tables_and_explicit_version(tmp_path):
    repository = _repository(tmp_path)
    try:
        assert repository.schema_version == SCHEMA_VERSION
        assert repository.business_tables() == BUSINESS_TABLES
        assert repository.journal_mode.lower() != "wal"
    finally:
        repository.close()


def test_reopen_runs_ordered_migrations_idempotently_and_rejects_future_schema(tmp_path):
    path = tmp_path / "castfabric.sqlite3"
    first = ContentRepository(path, clock=lambda: NOW)
    first.close()
    second = ContentRepository(path, clock=lambda: NOW)
    assert second.schema_version == SCHEMA_VERSION
    second.close()

    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="UNSUPPORTED_SCHEMA_VERSION"):
        ContentRepository(path, clock=lambda: NOW)


def test_schema_enforces_foreign_keys_and_one_active_run_and_session_per_target(tmp_path):
    repository = _repository(tmp_path)
    path = repository.path
    repository.close()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO playlist_items "
                "(id, playlist_id, asset_id, position, created_at) "
                "VALUES ('item', 'missing-playlist', 'missing-asset', 0, ?)",
                (NOW.isoformat(),),
            )

        connection.execute(
            "INSERT INTO playlists "
            "(id, name, default_order, default_repeat, revision, created_at, updated_at) "
            "VALUES ('playlist', 'Morning', 'sequential', 'none', 1, ?, ?)",
            (NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO playback_runs "
            "(id, target_id, playlist_id, order_mode, repeat_mode, cycle_number, state, started_at, updated_at) "
            "VALUES ('run-1', 'uuid:living', 'playlist', 'sequential', 'none', 0, 'active', ?, ?)",
            (NOW.isoformat(), NOW.isoformat()),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO playback_runs "
                "(id, target_id, playlist_id, order_mode, repeat_mode, cycle_number, state, started_at, updated_at) "
                "VALUES ('run-2', 'uuid:living', 'playlist', 'sequential', 'none', 0, 'active', ?, ?)",
                (NOW.isoformat(), NOW.isoformat()),
            )
        connection.execute(
            "INSERT INTO media_sessions "
            "(id, run_id, target_id, source_type, state, seek_supported, started_at, updated_at) "
            "VALUES ('session-1', 'run-1', 'uuid:living', 'playlist', 'playing', 1, ?, ?)",
            (NOW.isoformat(), NOW.isoformat()),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO media_sessions "
                "(id, target_id, source_type, state, seek_supported, started_at, updated_at) "
                "VALUES ('session-2', 'uuid:living', 'url', 'starting', 0, ?, ?)",
                (NOW.isoformat(), NOW.isoformat()),
            )


def test_two_targets_store_independent_playlist_progress(tmp_path):
    repository = _repository(tmp_path)
    try:
        repository.create_playlist_record("playlist", "Morning")
        repository.create_run("run-living", "uuid:living", "playlist")
        repository.create_run("run-study", "uuid:study", "playlist")
        repository.create_session(
            "session-living", "uuid:living", source_type="playlist", run_id="run-living"
        )
        repository.create_session(
            "session-study", "uuid:study", source_type="playlist", run_id="run-study"
        )
        assert repository.update_session_progress("session-living", 12, duration_seconds=40)
        assert repository.update_session_progress("session-study", 31, duration_seconds=40)

        assert repository.get_session("session-living")["position_seconds"] == 12
        assert repository.get_session("session-study")["position_seconds"] == 31
    finally:
        repository.close()


def test_restart_marks_active_rows_interrupted_without_creating_new_rows(tmp_path):
    repository = _repository(tmp_path)
    repository.create_playlist_record("playlist", "Morning")
    repository.create_run("run", "uuid:living", "playlist")
    repository.create_session(
        "session", "uuid:living", source_type="playlist", run_id="run"
    )
    repository.close()

    reopened = _repository(tmp_path)
    try:
        assert reopened.interrupt_active_playback() == {"runs": 1, "sessions": 1}
        assert reopened.active_run("uuid:living") is None
        assert reopened.active_session("uuid:living") is None
        assert reopened.get_run("run")["end_reason"] == "interrupted"
        assert reopened.get_session("session")["end_reason"] == "interrupted"
        assert reopened.interrupt_active_playback() == {"runs": 0, "sessions": 0}
    finally:
        reopened.close()


def test_session_and_run_updates_are_fenced_by_current_ids(tmp_path):
    repository = _repository(tmp_path)
    try:
        repository.create_playlist_record("playlist", "Morning")
        repository.create_run("run-old", "uuid:living", "playlist")
        repository.create_session(
            "session-old", "uuid:living", source_type="playlist", run_id="run-old"
        )
        repository.end_session("session-old", "preempted")
        repository.end_run("run-old", "preempted")
        repository.create_run("run-new", "uuid:living", "playlist")
        repository.create_session(
            "session-new", "uuid:living", source_type="playlist", run_id="run-new"
        )

        assert repository.update_session_progress("session-old", 99) is False
        assert repository.end_run("run-old", "stopped") is False
        assert repository.get_session("session-new")["position_seconds"] is None
        assert repository.active_run("uuid:living")["id"] == "run-new"
    finally:
        repository.close()
