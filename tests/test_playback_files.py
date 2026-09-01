import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from miair.playback.files import EphemeralMediaStore, FilePlaybackError


async def _chunks(*items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_one_time_upload_uses_opaque_paths_and_starts_existing_playback(tmp_path):
    play_url = AsyncMock(return_value={
        "ok": True,
        "target_id": "uuid:living",
        "session_id": "session-file",
        "state": "playing",
    })
    playback = SimpleNamespace(controller_for=lambda _target_id: object(), play_url=play_url)
    store = EphemeralMediaStore(playback, directory=tmp_path, id_factory=iter([
        "upload-secret-token",
        "media-secret-token",
    ]).__next__)

    transaction = store.create_upload(
        "uuid:living",
        "../../private/notice.mp3",
        "audio/mpeg",
        6,
    )
    result = await store.accept_upload(
        transaction["upload_id"],
        _chunks(b"abc", b"def"),
        origin="http://castfabric.test:9988",
    )

    assert transaction["upload_path"] == "/api/v1/playback/files/upload-secret-token"
    assert "notice.mp3" not in transaction["upload_path"]
    assert result["state"] == "playing"
    playback.play_url.assert_awaited_once_with(
        "uuid:living",
        "http://castfabric.test:9988/api/v1/playback/media/media-secret-token",
        media_format="audio/mpeg",
    )
    media = store.resolve_media("media-secret-token")
    assert media.path.read_bytes() == b"abcdef"
    assert media.filename == "notice.mp3"
    pulled, first_pull = store.confirm_pull("media-secret-token")
    pulled_again, second_pull = store.confirm_pull("media-secret-token")
    assert pulled is media
    assert pulled_again is media
    assert first_pull is True
    assert second_pull is False

    with pytest.raises(FilePlaybackError) as replayed:
        await store.accept_upload(
            transaction["upload_id"],
            _chunks(b"abcdef"),
            origin="http://castfabric.test:9988",
        )
    assert replayed.value.code == "UPLOAD_NOT_FOUND"


@pytest.mark.asyncio
async def test_upload_size_mismatch_and_failed_playback_leave_no_file(tmp_path):
    playback = SimpleNamespace(
        controller_for=lambda _target_id: object(),
        play_url=AsyncMock(side_effect=RuntimeError("private target failure")),
    )
    store = EphemeralMediaStore(playback, directory=tmp_path)
    short = store.create_upload("uuid:living", "clip.wav", "audio/wav", 4)

    with pytest.raises(FilePlaybackError) as mismatch:
        await store.accept_upload(
            short["upload_id"], _chunks(b"abc"), origin="http://castfabric.test"
        )
    assert mismatch.value.code == "UPLOAD_SIZE_MISMATCH"
    assert not list(tmp_path.iterdir())

    failed = store.create_upload("uuid:living", "clip.wav", "audio/wav", 3)
    with pytest.raises(RuntimeError, match="private target failure"):
        await store.accept_upload(
            failed["upload_id"], _chunks(b"abc"), origin="http://castfabric.test"
        )
    assert not list(tmp_path.iterdir())


def test_invalid_file_metadata_is_rejected_before_creating_a_transaction(tmp_path):
    playback = SimpleNamespace(controller_for=lambda _target_id: object())
    store = EphemeralMediaStore(playback, directory=tmp_path, max_bytes=8)

    for size in (0, 9):
        with pytest.raises(FilePlaybackError) as error:
            store.create_upload("uuid:living", "clip.wav", "audio/wav", size)
        assert error.value.code == "INVALID_FILE_SIZE"

    with pytest.raises(FilePlaybackError) as error:
        store.resolve_media("unknown")
    assert error.value.code == "MEDIA_NOT_FOUND"


@pytest.mark.asyncio
async def test_ephemeral_media_expires_without_waiting_for_another_request(tmp_path):
    playback = SimpleNamespace(
        controller_for=lambda _target_id: object(),
        play_url=AsyncMock(return_value={"ok": True}),
    )
    store = EphemeralMediaStore(
        playback,
        directory=tmp_path,
        media_ttl=0.01,
        id_factory=iter(["upload-token", "media-token"]).__next__,
    )
    transaction = store.create_upload("uuid:living", "clip.wav", "audio/wav", 3)
    await store.accept_upload(
        transaction["upload_id"],
        _chunks(b"abc"),
        origin="http://castfabric.test",
    )

    await asyncio.sleep(0.03)

    with pytest.raises(FilePlaybackError) as expired:
        store.resolve_media("media-token")
    assert expired.value.code == "MEDIA_NOT_FOUND"
    assert not list(tmp_path.iterdir())
