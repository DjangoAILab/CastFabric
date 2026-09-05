from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from miair.content.media import MediaAssetService
from miair.content.playlists import PlaylistRunner, PlaylistService
from miair.content.repository import ContentRepository
from miair.playback.service import PlaybackService
from miair.runtime.sessions import MediaSessionCoordinator
from miair.runtime.suites import ReceiverSuiteRegistry
from miair.targets import OutputTargetConfig


def _runtime(tmp_path, *, accepted=True):
    repository = ContentRepository(tmp_path / "castfabric.sqlite3")
    assets = MediaAssetService(
        repository,
        tmp_path / "media",
        id_factory=iter(["asset-one", "asset-two", "asset-three"]).__next__,
    )
    playlists = PlaylistService(
        repository,
        id_factory=iter(["playlist", "item-one", "item-two", "item-three"]).__next__,
    )
    for index, name in enumerate(("One", "Two", "Three"), 1):
        assets.create_external_url(f"https://example.test/{index}.mp3", display_name=name)
    playlists.create_playlist("Morning")
    one = playlists.add_item("playlist", "asset-one", expected_revision=1)
    two = playlists.add_item("playlist", "asset-two", expected_revision=2)
    three = playlists.add_item("playlist", "asset-three", expected_revision=3)

    suites = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    controllers = {}
    for target_id in ("uuid:living", "uuid:study"):
        target = OutputTargetConfig(
            id=target_id,
            name=target_id.rsplit(":", 1)[-1],
            virtual_udn=target_id + "-virtual",
        )
        controller = SimpleNamespace(
            play_url=AsyncMock(return_value=accepted),
            pause=AsyncMock(return_value=True),
            resume=AsyncMock(return_value=True),
            stop=AsyncMock(return_value=True),
            set_volume=AsyncMock(return_value=True),
            seek=AsyncMock(return_value=True),
            get_status=AsyncMock(
                return_value={
                    "state": "playing",
                    "position_seconds": 0,
                    "duration_seconds": 10,
                    "seek_supported": True,
                }
            ),
        )
        suites.register(target, target_id, controller)
        controllers[target_id] = controller
    coordinator = MediaSessionCoordinator(repository=repository)
    playback = PlaybackService(suites, coordinator)
    runner = PlaylistRunner(
        repository,
        playlists,
        assets,
        playback,
        media_origin="http://castfabric.test:8300",
        auto_monitor=False,
        id_factory=iter(
            [
                "run-living", "session-living-1", "session-living-2", "session-living-3",
                "run-study", "session-study-1", "session-study-2", "session-study-3",
            ]
        ).__next__,
    )
    playlists.conflict_handler = runner.resolve_definition_conflict
    return repository, assets, playlists, runner, controllers, (one, two, three)


@pytest.mark.asyncio
async def test_sequential_runner_advances_and_completes_without_client_polling(tmp_path):
    repository, _assets, _playlists, runner, controllers, items = _runtime(tmp_path)
    try:
        started = await runner.start_playlist("playlist", "uuid:living")
        assert started["run_id"] == "run-living"
        controllers["uuid:living"].play_url.assert_awaited_once_with(
            "https://example.test/1.mp3", play_type=2
        )

        controllers["uuid:living"].get_status.return_value = {
            "state": "stopped", "position_seconds": 10, "duration_seconds": 10
        }
        advanced = await runner.observe_once("run-living")
        assert advanced["current_item"]["id"] == items[1]["id"]
        assert controllers["uuid:living"].play_url.await_count == 2

        await runner.observe_once("run-living")
        await runner.observe_once("run-living")
        assert repository.get_run("run-living")["end_reason"] == "completed"
        assert repository.active_session("uuid:living") is None
    finally:
        await runner.close()
        repository.close()


@pytest.mark.asyncio
async def test_renderer_still_playing_at_exact_eof_advances_and_stops(tmp_path):
    repository, _assets, _playlists, runner, controllers, items = _runtime(tmp_path)
    try:
        started = await runner.start_playlist("playlist", "uuid:living")
        controller = controllers["uuid:living"]
        controller.get_status.return_value = {
            "state": "playing", "position_seconds": 9.9, "duration_seconds": 10
        }
        await runner.observe_once(started["run_id"])
        assert controller.play_url.await_count == 1
        controller.get_status.return_value["position_seconds"] = 10
        advanced = await runner.observe_once(started["run_id"])
        assert advanced["current_item"]["id"] == items[1]["id"]
        await runner.observe_once(started["run_id"])
        await runner.observe_once(started["run_id"])
        assert repository.get_run(started["run_id"])["end_reason"] == "completed"
        assert controller.stop.await_count == 3
    finally:
        await runner.close()
        repository.close()


@pytest.mark.asyncio
async def test_same_playlist_on_two_targets_keeps_independent_progress(tmp_path):
    repository, _assets, _playlists, runner, controllers, _items = _runtime(tmp_path)
    try:
        living = await runner.start_playlist("playlist", "uuid:living")
        study = await runner.start_playlist("playlist", "uuid:study")
        controllers["uuid:living"].get_status.return_value = {
            "state": "playing", "position_seconds": 7, "duration_seconds": 10
        }
        controllers["uuid:study"].get_status.return_value = {
            "state": "playing", "position_seconds": 2, "duration_seconds": 10
        }
        await runner.observe_once(living["run_id"])
        await runner.observe_once(study["run_id"])

        assert runner.get_run(living["run_id"])["position_seconds"] == 7
        assert runner.get_run(study["run_id"])["position_seconds"] == 2
    finally:
        await runner.close()
        repository.close()


@pytest.mark.asyncio
async def test_failure_stops_on_current_item_without_skip_retry_or_fallback(tmp_path):
    repository, _assets, _playlists, runner, controllers, _items = _runtime(tmp_path)
    try:
        started = await runner.start_playlist("playlist", "uuid:living")
        controllers["uuid:living"].get_status.side_effect = RuntimeError("offline")
        result = await runner.observe_once(started["run_id"])

        assert result["state"] == "ended"
        assert result["end_reason"] == "failed"
        assert controllers["uuid:living"].play_url.await_count == 1
        controllers["uuid:living"].stop.assert_awaited_once()
        assert repository.active_session("uuid:living") is None
    finally:
        await runner.close()
        repository.close()


@pytest.mark.asyncio
async def test_ambiguous_early_stop_interrupts_instead_of_advancing(tmp_path):
    repository, _assets, _playlists, runner, controllers, _items = _runtime(tmp_path)
    try:
        started = await runner.start_playlist("playlist", "uuid:living")
        controllers["uuid:living"].get_status.return_value = {
            "state": "stopped", "position_seconds": 2, "duration_seconds": 10
        }
        result = await runner.observe_once(started["run_id"])
        assert result["end_reason"] == "interrupted"
        assert controllers["uuid:living"].play_url.await_count == 1
    finally:
        await runner.close()
        repository.close()


@pytest.mark.asyncio
async def test_controls_are_fenced_and_navigation_uses_server_history(tmp_path):
    repository, _assets, _playlists, runner, controllers, items = _runtime(tmp_path)
    try:
        started = await runner.start_playlist("playlist", "uuid:living")
        with pytest.raises(Exception) as stale:
            await runner.control(started["run_id"], "seek", position_seconds=4, if_session_id="old")
        assert getattr(stale.value, "reason", None) == "SESSION_CHANGED"
        controllers["uuid:living"].seek.assert_not_awaited()

        selected = await runner.control(started["run_id"], "select", item_id=items[2]["id"])
        assert selected["current_item"]["id"] == items[2]["id"]
        previous = await runner.control(started["run_id"], "previous")
        assert previous["current_item"]["id"] == items[0]["id"]
        await runner.control(started["run_id"], "pause")
        await runner.control(started["run_id"], "resume")
        controllers["uuid:living"].pause.assert_awaited_once()
        controllers["uuid:living"].resume.assert_awaited_once()
    finally:
        await runner.close()
        repository.close()


@pytest.mark.asyncio
async def test_explicit_resume_validates_candidate_and_seeks_selected_item(tmp_path):
    repository, _assets, _playlists, runner, controllers, items = _runtime(tmp_path)
    try:
        first = await runner.start_playlist("playlist", "uuid:living")
        session_id = first["session_id"]
        await runner.control(first["run_id"], "stop")
        assert repository.update_ended_session_progress(session_id, 6)

        resumed = await runner.start_playlist(
            "playlist",
            "uuid:living",
            start_item_id=items[0]["id"],
            start_position_seconds=6,
            resumed_from_session_id=session_id,
        )
        assert resumed["current_item"]["id"] == items[0]["id"]
        controllers["uuid:living"].seek.assert_awaited_with(6)
    finally:
        await runner.close()
        repository.close()


@pytest.mark.asyncio
async def test_random_uses_unplayed_items_and_repeat_all_starts_a_new_cycle(tmp_path):
    repository, _assets, playlists, runner, controllers, items = _runtime(tmp_path)
    playlists.randomizer.choice = lambda choices: choices[-1]
    try:
        random_run = await runner.start_playlist(
            "playlist", "uuid:living", order_mode="random"
        )
        assert random_run["current_item"]["id"] == items[2]["id"]
        controllers["uuid:living"].get_status.return_value = {
            "state": "stopped", "position_seconds": 10, "duration_seconds": 10
        }
        random_next = await runner.observe_once(random_run["run_id"])
        assert random_next["current_item"]["id"] == items[1]["id"]

        repeated = await runner.start_playlist(
            "playlist", "uuid:study", repeat_mode="all"
        )
        controllers["uuid:study"].get_status.return_value = {
            "state": "stopped", "position_seconds": 10, "duration_seconds": 10
        }
        await runner.observe_once(repeated["run_id"])
        await runner.observe_once(repeated["run_id"])
        next_cycle = await runner.observe_once(repeated["run_id"])
        assert next_cycle["state"] == "active"
        assert next_cycle["cycle_number"] == 1
        assert next_cycle["current_item"]["id"] == items[0]["id"]
    finally:
        await runner.close()
        repository.close()


@pytest.mark.asyncio
async def test_ordinary_playback_preempts_playlist_and_live_edit_requires_resolution(tmp_path):
    repository, _assets, playlists, runner, controllers, items = _runtime(tmp_path)
    runner.playback.before_play = runner.preempt_target
    try:
        started = await runner.start_playlist("playlist", "uuid:living")
        with pytest.raises(Exception) as conflict:
            await playlists.update_item(
                "playlist", items[0]["id"], expected_revision=4, asset_id="asset-two"
            )
        assert getattr(conflict.value, "reason", None) == "ACTIVE_PLAYBACK_CONFLICT"
        assert controllers["uuid:living"].play_url.await_count == 1

        changed = await playlists.update_item(
            "playlist", items[0]["id"], expected_revision=4,
            asset_id="asset-two", resolution="reload",
        )
        assert changed["items"][0]["asset_id"] == "asset-two"
        assert controllers["uuid:living"].play_url.await_count == 2

        await runner.playback.play_url("uuid:living", "https://example.test/ordinary.mp3")
        assert repository.get_run(started["run_id"])["end_reason"] == "preempted"
        assert repository.active_run("uuid:living") is None
    finally:
        await runner.close()
        repository.close()
