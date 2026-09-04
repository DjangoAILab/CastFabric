import random

import pytest

from miair.content.media import ContentServiceError, MediaAssetService
from miair.content.playlists import PlaylistService
from miair.content.repository import ContentRepository


def _services(tmp_path):
    repository = ContentRepository(tmp_path / "castfabric.sqlite3")
    asset_ids = iter(["asset-one", "asset-two", "asset-three"])
    assets = MediaAssetService(repository, tmp_path / "media", id_factory=asset_ids.__next__)
    playlists = PlaylistService(
        repository,
        id_factory=iter(["playlist", "item-one", "item-two", "item-three"]).__next__,
        randomizer=random.Random(7),
    )
    for index, name in enumerate(("Opening", "Middle", "Closing"), 1):
        assets.create_external_url(f"https://example.test/{index}.mp3", display_name=name)
    return repository, assets, playlists


def test_playlist_crud_items_title_fallback_reorder_and_revision(tmp_path):
    repository, _assets, service = _services(tmp_path)
    try:
        playlist = service.create_playlist(
            "Morning",
            description="Weekdays",
            default_order="sequential",
            default_repeat="none",
        )
        assert playlist["revision"] == 1
        first = service.add_item("playlist", "asset-one", expected_revision=1)
        second = service.add_item(
            "playlist", "asset-two", title="Custom middle", expected_revision=2
        )
        detail = service.get_playlist("playlist")
        assert detail["revision"] == 3
        assert [item["title"] for item in detail["items"]] == ["Opening", "Custom middle"]
        assert [item["title_override"] for item in detail["items"]] == [None, "Custom middle"]

        reordered = service.reorder_items(
            "playlist", [second["id"], first["id"]], expected_revision=3
        )
        assert [item["id"] for item in reordered["items"]] == [second["id"], first["id"]]
        assert [item["position"] for item in reordered["items"]] == [0, 1]
        updated = service.update_playlist(
            "playlist",
            expected_revision=4,
            name="Morning focus",
            default_order="random",
            default_repeat="all",
        )
        assert updated["name"] == "Morning focus"
        assert updated["description"] == "Weekdays"
        assert updated["revision"] == 5
    finally:
        repository.close()


def test_revision_conflict_never_changes_definition(tmp_path):
    repository, _assets, service = _services(tmp_path)
    try:
        service.create_playlist("Morning")
        with pytest.raises(ContentServiceError) as conflict:
            service.add_item("playlist", "asset-one", expected_revision=9)
        assert conflict.value.code == "CONFLICT"
        assert conflict.value.reason == "PLAYLIST_REVISION_CHANGED"
        assert conflict.value.details["current_revision"] == 1
        assert service.get_playlist("playlist")["items"] == []
    finally:
        repository.close()


@pytest.mark.asyncio
async def test_only_current_item_mutations_raise_one_structured_active_conflict(tmp_path):
    repository, _assets, service = _services(tmp_path)
    try:
        service.create_playlist("Morning")
        first = service.add_item("playlist", "asset-one", expected_revision=1)
        second = service.add_item("playlist", "asset-two", expected_revision=2)
        repository.create_run("run", "uuid:living", "playlist")
        repository.create_session(
            "session",
            "uuid:living",
            source_type="playlist",
            run_id="run",
            asset_id="asset-one",
            playlist_item_id=first["id"],
        )

        service.reorder_items(
            "playlist", [second["id"], first["id"]], expected_revision=3
        )
        with pytest.raises(ContentServiceError) as removing:
            await service.remove_item("playlist", first["id"], expected_revision=4)
        assert removing.value.code == "CONFLICT"
        assert removing.value.reason == "ACTIVE_PLAYBACK_CONFLICT"
        assert removing.value.details == {
            "affected_runs": [
                {"run_id": "run", "target_id": "uuid:living", "session_id": "session"}
            ],
            "allowed_resolutions": ["keep", "reload", "stop"],
        }

        removed = await service.remove_item(
            "playlist", first["id"], expected_revision=4, resolution="keep"
        )
        assert [item["id"] for item in removed["items"]] == [second["id"]]
        assert repository.get_session("session")["state"] == "starting"
    finally:
        repository.close()


@pytest.mark.asyncio
async def test_replacing_current_asset_and_archiving_share_conflict_handler(tmp_path):
    repository, _assets, service = _services(tmp_path)
    calls = []

    async def handle(resolution, conflicts, action):
        calls.append((resolution, conflicts, action))

    service.conflict_handler = handle
    try:
        service.create_playlist("Morning")
        item = service.add_item("playlist", "asset-one", expected_revision=1)
        repository.create_run("run", "uuid:living", "playlist")
        repository.create_session(
            "session",
            "uuid:living",
            source_type="playlist",
            run_id="run",
            asset_id="asset-one",
            playlist_item_id=item["id"],
        )

        changed = await service.update_item(
            "playlist",
            item["id"],
            expected_revision=2,
            asset_id="asset-two",
            resolution="reload",
        )
        assert changed["items"][0]["asset_id"] == "asset-two"
        archived = await service.archive_playlist(
            "playlist", expected_revision=3, resolution="stop"
        )
        assert archived["archived_at"] is not None
        assert [call[0] for call in calls] == ["reload", "stop"]
        assert [call[2] for call in calls] == ["replace_current_item", "archive_playlist"]
    finally:
        repository.close()


def test_next_reads_live_definition_previous_reads_actual_history_and_random_uses_cycle_history(tmp_path):
    repository, _assets, service = _services(tmp_path)
    try:
        service.create_playlist("Morning")
        one = service.add_item("playlist", "asset-one", expected_revision=1)
        two = service.add_item("playlist", "asset-two", expected_revision=2)
        three = service.add_item("playlist", "asset-three", expected_revision=3)
        repository.create_run("run", "uuid:living", "playlist")
        repository.create_session(
            "session-one", "uuid:living", source_type="playlist", run_id="run",
            asset_id="asset-one", playlist_item_id=one["id"], cycle_number=0,
        )
        repository.end_session("session-one", "completed")
        repository.create_session(
            "session-two", "uuid:living", source_type="playlist", run_id="run",
            asset_id="asset-two", playlist_item_id=two["id"], cycle_number=0,
        )

        service.reorder_items(
            "playlist", [one["id"], three["id"], two["id"]], expected_revision=4
        )
        assert service.next_item("run", two["id"]) is None
        assert service.previous_item("run")["playlist_item_id"] == one["id"]

        repository.set_run_modes("run", order_mode="random", repeat_mode="none")
        random_next = service.next_item("run", two["id"])
        assert random_next["id"] == three["id"]
    finally:
        repository.close()
