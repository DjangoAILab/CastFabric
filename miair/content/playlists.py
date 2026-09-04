"""Playlist definitions and live-definition navigation rules."""

from __future__ import annotations

import inspect
import random
import secrets
from typing import Any, Callable

from miair.content.media import ContentServiceError


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
        if self.conflict_handler is not None:
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
        if title is not _UNSET:
            values["title"] = str(title).strip()[:200] if title else None
        if asset_id is not None:
            asset = self.repository.get_media_asset(asset_id)
            if asset is None or asset["status"] == "deleted":
                raise ContentServiceError("NOT_FOUND", "ASSET_NOT_FOUND", {"asset_id": asset_id})
            if asset_id != current["asset_id"]:
                await self._resolve(
                    self._conflicts(playlist_id, item_id), resolution, "replace_current_item"
                )
            values["asset_id"] = asset_id
        status, revision = self.repository.update_playlist_item(
            playlist_id, item_id, expected_revision, values
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
        return self.get_playlist(playlist_id)

    async def remove_item(
        self,
        playlist_id: str,
        item_id: str,
        *,
        expected_revision: int,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        await self._resolve(
            self._conflicts(playlist_id, item_id), resolution, "remove_current_item"
        )
        status, revision = self.repository.remove_playlist_item(
            playlist_id, item_id, expected_revision
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
        return self.get_playlist(playlist_id)

    async def archive_playlist(
        self,
        playlist_id: str,
        *,
        expected_revision: int,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        await self._resolve(
            self._conflicts(playlist_id), resolution, "archive_playlist"
        )
        status, revision = self.repository.archive_playlist_record(
            playlist_id, expected_revision
        )
        if status != "ok":
            self._mutation_error(status, revision, playlist_id)
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
        if run["repeat_mode"] == "all":
            next_cycle = int(run["cycle_number"]) + 1
            self.repository.set_run_cycle(run_id, next_cycle)
            return self.randomizer.choice(items) if run["order_mode"] == "random" else items[0]
        return None
