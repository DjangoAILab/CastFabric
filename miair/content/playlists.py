"""Playlist definitions and live-definition navigation rules."""

from __future__ import annotations

import asyncio
import inspect
import random
import secrets
from datetime import datetime, timezone
from typing import Any, Callable

from miair.content.media import ContentServiceError
from miair.playback.service import PlaybackServiceError


_UNSET = object()


class PlaylistService:
    def __init__(
        self,
        repository,
        *,
        id_factory: Callable[[], str] = lambda: secrets.token_urlsafe(18),
        randomizer: random.Random | None = None,
        conflict_handler=None,
    ):
        self.repository = repository
        self.id_factory = id_factory
        self.randomizer = randomizer or random.Random()
        self.conflict_handler = conflict_handler

    @staticmethod
    def _name(value: str) -> str:
        name = str(value or "").strip()
        if not name or len(name) > 200:
            raise ContentServiceError("INVALID_INPUT", "INVALID_PLAYLIST_NAME")
        return name

    @staticmethod
    def _description(value: str | None) -> str | None:
        return str(value).strip()[:1000] if value else None

    @staticmethod
    def _modes(order: str, repeat: str) -> tuple[str, str]:
        if order not in {"sequential", "random"}:
            raise ContentServiceError("INVALID_INPUT", "INVALID_ORDER_MODE")
        if repeat not in {"none", "all"}:
            raise ContentServiceError("INVALID_INPUT", "INVALID_REPEAT_MODE")
        return order, repeat

    def _item(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "playlist_id": row["playlist_id"],
            "asset_id": row["asset_id"],
            "position": row["position"],
            "title": row.get("title") or row.get("asset_display_name"),
            "title_override": row.get("title"),
            "asset_status": row.get("asset_status"),
            "source_kind": row.get("source_kind"),
            "content_type": row.get("content_type"),
            "size_bytes": row.get("size_bytes"),
            "duration_seconds": row.get("duration_seconds"),
        }

    def _detail(self, row: dict[str, Any]) -> dict[str, Any]:
        items = [self._item(item) for item in self.repository.playlist_items(row["id"])]
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row.get("description"),
            "default_order": row["default_order"],
            "default_repeat": row["default_repeat"],
            "revision": row["revision"],
            "archived_at": row.get("archived_at"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "item_count": len(items),
            "total_duration_seconds": sum(
                item["duration_seconds"] or 0 for item in items
            ),
            "items": items,
        }

    def create_playlist(
        self,
        name: str,
        *,
        description: str | None = None,
        default_order: str = "sequential",
        default_repeat: str = "none",
    ) -> dict[str, Any]:
        order, repeat = self._modes(default_order, default_repeat)
        row = self.repository.create_playlist_record(
            self.id_factory(),
            self._name(name),
            description=self._description(description),
            default_order=order,
            default_repeat=repeat,
        )
        return self._detail(row)

    def get_playlist(self, playlist_id: str, *, include_archived: bool = False) -> dict[str, Any]:
        row = self.repository.get_playlist(str(playlist_id))
        if row is None or (row["archived_at"] and not include_archived):
            raise ContentServiceError("NOT_FOUND", "PLAYLIST_NOT_FOUND", {"playlist_id": playlist_id})
        return self._detail(row)

    def list_playlists(self) -> dict[str, Any]:
        rows = self.repository.list_playlists()
        items = [self._detail(row) for row in rows]
        return {"items": items, "total": len(items)}

    def _mutation_error(self, status: str, revision: int | None, playlist_id: str):
        if status == "missing":
            raise ContentServiceError("NOT_FOUND", "PLAYLIST_NOT_FOUND", {"playlist_id": playlist_id})
        if status == "item_missing":
            raise ContentServiceError("NOT_FOUND", "PLAYLIST_ITEM_NOT_FOUND")
        raise ContentServiceError(
            "CONFLICT",
            "PLAYLIST_REVISION_CHANGED",
            {"playlist_id": playlist_id, "current_revision": revision},
        )

    def update_playlist(
        self,
        playlist_id: str,
        *,
        expected_revision: int,
        name: str | None = None,
        description: str | None | object = _UNSET,
        default_order: str | None = None,
        default_repeat: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_playlist(playlist_id)
        order, repeat = self._modes(
            default_order or current["default_order"],
            default_repeat or current["default_repeat"],
        )
        values = {
            "name": self._name(name if name is not None else current["name"]),
            "description": (
                current["description"]
                if description is _UNSET
                else self._description(description)
            ),
            "default_order": order,
            "default_repeat": repeat,
        }
        status, revision = self.repository.update_playlist_record(
            playlist_id, expected_revision, values
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
        return self.get_playlist(playlist_id)

    def add_item(
        self,
        playlist_id: str,
        asset_id: str,
        *,
        expected_revision: int,
        title: str | None = None,
    ) -> dict[str, Any]:
        asset = self.repository.get_media_asset(str(asset_id))
        if asset is None or asset["status"] == "deleted":
            raise ContentServiceError("NOT_FOUND", "ASSET_NOT_FOUND", {"asset_id": asset_id})
        item_id = self.id_factory()
        status, revision = self.repository.add_playlist_item(
            item_id,
            playlist_id,
            asset_id,
            str(title).strip()[:200] if title else None,
            expected_revision,
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
        return next(item for item in self.get_playlist(playlist_id)["items"] if item["id"] == item_id)

    def reorder_items(
        self, playlist_id: str, ordered_ids: list[str], *, expected_revision: int
    ) -> dict[str, Any]:
        status, revision = self.repository.reorder_playlist_items(
            playlist_id, list(ordered_ids), expected_revision
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
        return self.get_playlist(playlist_id)

    def _conflicts(self, playlist_id: str, item_id: str | None = None) -> list[dict[str, Any]]:
        return self.repository.active_item_conflicts(
            playlist_id=playlist_id, item_id=item_id
        )

    async def _resolve(
        self,
        conflicts: list[dict[str, Any]],
        resolution: str | None,
        action: str,
    ) -> None:
        if not conflicts:
            return
        details = {
            "affected_runs": conflicts,
            "allowed_resolutions": ["keep", "reload", "stop"],
        }
        if resolution not in details["allowed_resolutions"]:
            raise ContentServiceError("CONFLICT", "ACTIVE_PLAYBACK_CONFLICT", details)
        if resolution == "stop" and self.conflict_handler is not None:
            result = self.conflict_handler(resolution, conflicts, action)
            if inspect.isawaitable(result):
                await result

    async def _apply_resolution(
        self, resolution: str | None, conflicts: list[dict[str, Any]], action: str
    ) -> None:
        if conflicts and resolution != "stop" and self.conflict_handler is not None:
            result = self.conflict_handler(resolution, conflicts, action)
            if inspect.isawaitable(result):
                await result

    async def update_item(
        self,
        playlist_id: str,
        item_id: str,
        *,
        expected_revision: int,
        asset_id: str | None = None,
        title: str | None | object = _UNSET,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        current = self.repository.get_playlist_item(item_id)
        if current is None or current["playlist_id"] != playlist_id or current["removed_at"]:
            raise ContentServiceError("NOT_FOUND", "PLAYLIST_ITEM_NOT_FOUND")
        values: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
        if title is not _UNSET:
            values["title"] = str(title).strip()[:200] if title else None
        if asset_id is not None:
            asset = self.repository.get_media_asset(asset_id)
            if asset is None or asset["status"] == "deleted":
                raise ContentServiceError("NOT_FOUND", "ASSET_NOT_FOUND", {"asset_id": asset_id})
            if asset_id != current["asset_id"]:
                conflicts = self._conflicts(playlist_id, item_id)
                await self._resolve(conflicts, resolution, "replace_current_item")
            values["asset_id"] = asset_id
        status, revision = self.repository.update_playlist_item(
            playlist_id, item_id, expected_revision, values
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
        await self._apply_resolution(resolution, conflicts, "replace_current_item")
        return self.get_playlist(playlist_id)

    async def remove_item(
        self,
        playlist_id: str,
        item_id: str,
        *,
        expected_revision: int,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        conflicts = self._conflicts(playlist_id, item_id)
        await self._resolve(conflicts, resolution, "remove_current_item")
        status, revision = self.repository.remove_playlist_item(
            playlist_id, item_id, expected_revision
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
        await self._apply_resolution(resolution, conflicts, "remove_current_item")
        return self.get_playlist(playlist_id)

    async def archive_playlist(
        self,
        playlist_id: str,
        *,
        expected_revision: int,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        conflicts = self._conflicts(playlist_id)
        await self._resolve(conflicts, resolution, "archive_playlist")
        status, revision = self.repository.archive_playlist_record(
            playlist_id, expected_revision
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
        await self._apply_resolution(resolution, conflicts, "archive_playlist")
        return self.get_playlist(playlist_id, include_archived=True)

    def previous_item(self, run_id: str) -> dict[str, Any] | None:
        sessions = self.repository.run_sessions(run_id)
        return next(
            (
                session
                for session in sessions
                if session["state"] == "ended"
                and session["playlist_item_id"]
                and session["end_reason"] in {"completed", "skipped"}
            ),
            None,
        )

    def next_item(self, run_id: str, current_item_id: str | None) -> dict[str, Any] | None:
        run = self.repository.get_run(run_id)
        if run is None or run["state"] != "active":
            raise ContentServiceError("NOT_FOUND", "RUN_NOT_FOUND", {"run_id": run_id})
        items = [self._item(item) for item in self.repository.playlist_items(run["playlist_id"])]
        if not items:
            return None
        if run["order_mode"] == "random":
            played = {
                session["playlist_item_id"]
                for session in self.repository.run_sessions(
                    run_id, cycle_number=run["cycle_number"]
                )
                if session["playlist_item_id"]
            }
            candidates = [item for item in items if item["id"] not in played]
            if candidates:
                return self.randomizer.choice(candidates)
        else:
            for index, item in enumerate(items):
                if item["id"] == current_item_id:
                    return items[index + 1] if index + 1 < len(items) else None
            if current_item_id is None:
                return items[0]
            removed = self.repository.get_playlist_item(current_item_id)
            if removed is not None and removed.get("removed_at"):
                successor = next(
                    (item for item in items if item["position"] >= removed["position"]), None
                )
                if successor is not None:
                    return successor
        if run["repeat_mode"] == "all":
            next_cycle = int(run["cycle_number"]) + 1
            self.repository.set_run_cycle(run_id, next_cycle)
            return self.randomizer.choice(items) if run["order_mode"] == "random" else items[0]
        return None


class PlaylistRunner:
    """Small server-side playlist state machine; SQLite remains the authority."""

    def __init__(
        self,
        repository,
        playlists: PlaylistService,
        media_assets,
        playback_service,
        *,
        media_origin: str,
        poll_interval: float = 2.0,
        auto_monitor: bool = True,
        id_factory: Callable[[], str] = lambda: secrets.token_urlsafe(18),
    ):
        self.repository = repository
        self.playlists = playlists
        self.media_assets = media_assets
        self.playback = playback_service
        self.media_origin = media_origin.rstrip("/")
        self.poll_interval = max(0.25, float(poll_interval))
        self.auto_monitor = auto_monitor
        self.id_factory = id_factory
        self._tasks: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _item(self, playlist_id: str, item_id: str) -> dict[str, Any] | None:
        playlist = self.playlists.get_playlist(playlist_id, include_archived=True)
        return next((item for item in playlist["items"] if item["id"] == item_id), None)

    def _source(self, item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        asset = self.repository.get_media_asset(item["asset_id"])
        if asset is None or asset["status"] != "available":
            raise ContentServiceError("UNAVAILABLE", "ASSET_UNAVAILABLE")
        resolved = self.media_assets.resolve_source(asset["id"])
        if asset["source_kind"] == "managed_file":
            resolved = f"{self.media_origin}/api/v1/media/assets/{asset['id']}/content"
        return resolved, asset

    def _project(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get_run(run_id)
        if run is None:
            raise ContentServiceError("NOT_FOUND", "RUN_NOT_FOUND", {"run_id": run_id})
        session = self.repository.active_session_for_run(run_id)
        current_item = None
        if session and session.get("playlist_item_id"):
            current_item = self._item(run["playlist_id"], session["playlist_item_id"])
            if current_item is None:
                current_item = {
                    "id": session["playlist_item_id"],
                    "asset_id": session.get("asset_id"),
                    "title": session.get("item_title_snapshot"),
                    "removed": True,
                }
        return {
            "run_id": run["id"],
            "target_id": run["target_id"],
            "playlist_id": run["playlist_id"],
            "state": run["state"],
            "end_reason": run.get("end_reason"),
            "order_mode": run["order_mode"],
            "repeat_mode": run["repeat_mode"],
            "cycle_number": run["cycle_number"],
            "session_id": session["id"] if session else None,
            "session_state": session["state"] if session else None,
            "current_item": current_item,
            "position_seconds": session.get("position_seconds") if session else None,
            "duration_seconds": session.get("duration_seconds") if session else None,
            "seek_supported": bool(session.get("seek_supported")) if session else False,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._project(run_id)

    def list_active_runs(self, *, playlist_id: str | None = None) -> dict[str, Any]:
        runs = self.repository.active_runs()
        if playlist_id:
            runs = [run for run in runs if run["playlist_id"] == playlist_id]
        return {"items": [self._project(run["id"]) for run in runs]}

    async def start_playlist(
        self,
        playlist_id: str,
        target_id: str,
        *,
        order_mode: str | None = None,
        repeat_mode: str | None = None,
        start_item_id: str | None = None,
        start_position_seconds: int = 0,
        resumed_from_session_id: str | None = None,
    ) -> dict[str, Any]:
        playlist = self.playlists.get_playlist(playlist_id)
        order, repeat = self.playlists._modes(
            order_mode or playlist["default_order"],
            repeat_mode or playlist["default_repeat"],
        )
        if not playlist["items"]:
            raise ContentServiceError("INVALID_INPUT", "PLAYLIST_EMPTY")
        item = next(
            (entry for entry in playlist["items"] if entry["id"] == start_item_id),
            playlist["items"][0] if start_item_id is None else None,
        )
        if item is None:
            raise ContentServiceError("NOT_FOUND", "PLAYLIST_ITEM_NOT_FOUND")
        if resumed_from_session_id:
            candidate = self.repository.get_session(resumed_from_session_id)
            if (
                candidate is None
                or candidate["state"] != "ended"
                or candidate["playlist_item_id"] != item["id"]
                or candidate["target_id"] != target_id
            ):
                raise ContentServiceError("CONFLICT", "RESUME_CANDIDATE_CHANGED")
        self.playback.controller_for(target_id)
        await self.preempt_target(target_id)
        source, asset = self._source(item)
        run_id, session_id = self.id_factory(), self.id_factory()
        self.repository.start_run_with_session(
            run_id, session_id, target_id, playlist_id,
            order_mode=order, repeat_mode=repeat, asset_id=asset["id"],
            playlist_item_id=item["id"], item_title_snapshot=item["title"],
            source_type="playlist", source_label=asset["display_name"],
            duration_seconds=asset.get("duration_seconds"), seek_supported=True,
            resumed_from_session_id=resumed_from_session_id,
        )
        if start_position_seconds:
            self.repository.update_session_progress(session_id, start_position_seconds)
        try:
            await self.playback.play_url(
                target_id, source, media_format=asset.get("content_type"),
                start_position_seconds=start_position_seconds, preempt=False,
                session_id=session_id, persist_session=False,
            )
        except Exception as exc:
            self.repository.end_session(
                session_id, "failed", error_code=getattr(exc, "code", "TARGET_COMMAND_FAILED")
            )
            self.repository.end_run(run_id, "failed")
            raise
        if self.auto_monitor:
            self._tasks[run_id] = asyncio.create_task(self._monitor(run_id))
        return self._project(run_id)

    async def _start_item(self, run: dict[str, Any], item: dict[str, Any]) -> None:
        source, asset = self._source(item)
        session_id = self.id_factory()
        self.repository.create_session(
            session_id, run["target_id"], source_type="playlist", run_id=run["id"],
            asset_id=asset["id"], playlist_item_id=item["id"],
            item_title_snapshot=item["title"], source_label=asset["display_name"],
            cycle_number=run["cycle_number"], duration_seconds=asset.get("duration_seconds"),
            seek_supported=True,
        )
        try:
            await self.playback.play_url(
                run["target_id"], source, media_format=asset.get("content_type"),
                preempt=False, session_id=session_id, persist_session=False,
            )
        except Exception as exc:
            self.repository.end_session(
                session_id, "failed", error_code=getattr(exc, "code", "TARGET_COMMAND_FAILED")
            )
            self.repository.end_run(run["id"], "failed")
            raise

    async def _finish(self, run_id: str, reason: str, *, error_code: str | None = None):
        run = self.repository.get_run(run_id)
        session = self.repository.active_session_for_run(run_id)
        if session:
            await self.playback.session_coordinator.end(
                session["id"], failed=reason == "failed", reason=reason
            )
            self.repository.end_session(session["id"], reason, error_code=error_code)
        self.repository.end_run(run_id, reason)
        task = self._tasks.pop(run_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        return self._project(run_id)

    async def observe_once(self, run_id: str) -> dict[str, Any]:
        async with self._locks.setdefault(run_id, asyncio.Lock()):
            run = self.repository.get_run(run_id)
            session = self.repository.active_session_for_run(run_id)
            if run is None or run["state"] != "active" or session is None:
                return self._project(run_id)
            try:
                status = await self.playback.get_status(run["target_id"])
            except Exception as exc:
                return await self._finish(
                    run_id, "failed", error_code=getattr(exc, "code", "TARGET_COMMAND_FAILED")
                )
            current = self.repository.active_session_for_run(run_id)
            if current is None or current["id"] != session["id"]:
                return self._project(run_id)
            if status.get("position_seconds") is not None:
                self.repository.update_session_progress(
                    session["id"], status["position_seconds"],
                    duration_seconds=status.get("duration_seconds"),
                )
            state = status.get("state")
            if state in {"playing", "paused", "starting"}:
                self.repository.transition_session(
                    session["id"], "paused" if state == "paused" else "playing"
                )
                return self._project(run_id)
            position = status.get("position_seconds")
            duration = status.get("duration_seconds")
            naturally_completed = (
                state == "stopped"
                and isinstance(position, (int, float))
                and isinstance(duration, (int, float))
                and duration > 0
                and position >= max(duration - 2, duration * 0.95)
            )
            if not naturally_completed:
                return await self._finish(run_id, "interrupted")
            await self.playback.session_coordinator.end(session["id"], reason="completed")
            self.repository.end_session(session["id"], "completed")
            next_item = self.playlists.next_item(run_id, session["playlist_item_id"])
            if next_item is None:
                return await self._finish(run_id, "completed")
            await self._start_item(self.repository.get_run(run_id), next_item)
            return self._project(run_id)

    async def _monitor(self, run_id: str) -> None:
        try:
            while self.repository.get_run(run_id)["state"] == "active":
                await asyncio.sleep(self.poll_interval)
                await self.observe_once(run_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._finish(run_id, "failed", error_code=getattr(exc, "code", "RUNNER_FAILED"))

    async def control(
        self, run_id: str, action: str, *, if_session_id: str | None = None,
        item_id: str | None = None, position_seconds: int | None = None,
    ) -> dict[str, Any]:
        async with self._locks.setdefault(run_id, asyncio.Lock()):
            run = self.repository.get_run(run_id)
            session = self.repository.active_session_for_run(run_id)
            if run is None or run["state"] != "active" or session is None:
                raise ContentServiceError("NOT_FOUND", "RUN_NOT_ACTIVE")
            if if_session_id is not None and session["id"] != if_session_id:
                raise ContentServiceError("CONFLICT", "SESSION_CHANGED")
            target_id = run["target_id"]
            try:
                if action == "pause":
                    await self.playback.pause(target_id)
                elif action == "resume":
                    await self.playback.resume(target_id)
                elif action == "seek":
                    await self.playback.seek(
                        target_id, position_seconds, if_session_id=session["id"]
                    )
                    self.repository.update_session_progress(session["id"], position_seconds)
                elif action == "stop":
                    await self.playback.stop(target_id, reason="stopped")
                    self.repository.end_run(run_id, "stopped")
                elif action in {"next", "previous", "select"}:
                    if action == "next":
                        item = self.playlists.next_item(run_id, session["playlist_item_id"])
                    elif action == "previous":
                        prior = self.playlists.previous_item(run_id)
                        item = self._item(run["playlist_id"], prior["playlist_item_id"]) if prior else None
                    else:
                        item = self._item(run["playlist_id"], str(item_id))
                    if item is None:
                        raise ContentServiceError("NOT_FOUND", "PLAYLIST_ITEM_NOT_FOUND")
                    await self.playback.stop(target_id, reason="skipped")
                    await self._start_item(self.repository.get_run(run_id), item)
                else:
                    raise ContentServiceError("INVALID_INPUT", "INVALID_PLAYBACK_ACTION")
            except PlaybackServiceError as exc:
                raise ContentServiceError("PLAYBACK_ERROR", exc.code) from exc
            return self._project(run_id)

    async def preempt_target(self, target_id: str) -> None:
        run = self.repository.active_run(target_id)
        if run is None:
            return
        task = self._tasks.pop(run["id"], None)
        if task and task is not asyncio.current_task():
            task.cancel()
        session = self.repository.active_session_for_run(run["id"])
        if session:
            await self.playback.session_coordinator.end(session["id"], reason="preempted")
            self.repository.end_session(session["id"], "preempted")
        self.repository.end_run(run["id"], "preempted")

    async def resolve_definition_conflict(
        self, resolution: str, conflicts: list[dict[str, Any]], action: str
    ) -> None:
        if resolution == "keep":
            return
        for conflict in conflicts:
            if resolution == "stop" or action == "archive_playlist":
                await self.control(conflict["run_id"], "stop")
            elif action == "remove_current_item":
                await self.control(conflict["run_id"], "next")
            else:
                current = self.repository.active_session_for_run(conflict["run_id"])
                await self.control(
                    conflict["run_id"], "select", item_id=current["playlist_item_id"]
                )

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for run_id in [row["id"] for row in self.repository.active_runs()]:
            await self._finish(run_id, "interrupted")
