import io
import wave

import pytest

from miair.content.media import ContentServiceError, MediaAssetService
from miair.content.repository import ContentRepository


def _wav_bytes(seconds=0.05):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * int(8000 * seconds))
    return output.getvalue()


async def _chunks(payload, split=None):
    split = split or len(payload)
    yield payload[:split]
    if split < len(payload):
        yield payload[split:]


def _service(tmp_path, **kwargs):
    repository = ContentRepository(tmp_path / "castfabric.sqlite3")
    service = MediaAssetService(repository, tmp_path / "media", **kwargs)
    return repository, service


def test_external_url_metadata_is_editable_but_public_views_are_redacted(tmp_path):
    repository, service = _service(tmp_path, id_factory=iter(["asset-url"]).__next__)
    try:
        created = service.create_external_url(
            "https://audio.example.test/show.mp3?token=private#chapter",
            display_name="Morning show",
            description="Daily intro",
            tags=["Radio", "radio", " Morning "],
        )
        assert created["id"] == "asset-url"
        assert created["tags"] == ["Radio", "Morning"]
        assert created["source_summary"] == "https://audio.example.test/show.mp3"
        assert "private" not in repr(created)
        assert service.resolve_source("asset-url").endswith("token=private#chapter")

        updated = service.update_asset(
            "asset-url",
            display_name="First light",
            description=None,
            tags=["Morning"],
            external_url="https://cdn.example.test/new.mp3?signature=secret",
        )
        assert updated["display_name"] == "First light"
        assert updated["description"] is None
        assert updated["source_summary"] == "https://cdn.example.test/new.mp3"
        assert "secret" not in repr(updated)
    finally:
        repository.close()


def test_asset_search_filter_sort_and_stable_offset_pagination(tmp_path):
    ids = iter(["asset-z", "asset-a", "asset-b"])
    repository, service = _service(tmp_path, id_factory=ids.__next__)
    try:
        service.create_external_url("https://example.test/z.mp3", display_name="Zulu", tags=["focus"])
        service.create_external_url("https://example.test/a.mp3", display_name="Alpha", description="Focus intro")
        service.create_external_url("https://example.test/b.mp3", display_name="Bravo", tags=["sleep"])

        first = service.list_assets(query="focus", sort="name", limit=1, offset=0)
        second = service.list_assets(query="focus", sort="name", limit=1, offset=1)
        assert first["total"] == 2
        assert [item["display_name"] for item in first["items"]] == ["Alpha"]
        assert [item["display_name"] for item in second["items"]] == ["Zulu"]
        assert service.list_assets(source_kind="managed_file")["total"] == 0
    finally:
        repository.close()


@pytest.mark.asyncio
async def test_persistent_upload_is_one_use_safe_and_deduplicates_blob_by_sha256(tmp_path):
    payload = _wav_bytes()
    ids = iter(["upload-one", "asset-one", "upload-two", "unused-asset"])
    repository, service = _service(tmp_path, id_factory=ids.__next__)
    try:
        first = service.begin_upload("../../Morning.wav", "application/octet-stream", len(payload))
        accepted = await service.accept_upload(first["upload_id"], _chunks(payload, 17))
        assert accepted["asset"]["id"] == "asset-one"
        assert accepted["asset"]["original_filename"] == "Morning.wav"
        assert accepted["asset"]["content_type"] == "audio/wav"
        assert accepted["deduplicated"] is False
        assert len(list((tmp_path / "media" / "blobs").iterdir())) == 1

        with pytest.raises(ContentServiceError) as reused:
            await service.accept_upload(first["upload_id"], _chunks(payload))
        assert reused.value.reason == "UPLOAD_NOT_FOUND"

        second = service.begin_upload("Copy.wav", "audio/wav", len(payload))
        duplicate = await service.accept_upload(second["upload_id"], _chunks(payload))
        assert duplicate["asset"]["id"] == "asset-one"
        assert duplicate["deduplicated"] is True
        assert len(list((tmp_path / "media" / "blobs").iterdir())) == 1
    finally:
        repository.close()


@pytest.mark.asyncio
async def test_expired_invalid_or_mismatched_upload_leaves_no_asset_or_part(tmp_path):
    now = [10.0]
    repository, service = _service(
        tmp_path,
        clock=lambda: now[0],
        upload_ttl=5,
        id_factory=iter(["expired", "invalid", "short"]).__next__,
    )
    try:
        expired = service.begin_upload("clip.wav", "audio/wav", 4)
        now[0] = 16.0
        with pytest.raises(ContentServiceError) as expiry:
            await service.accept_upload(expired["upload_id"], _chunks(b"RIFF"))
        assert expiry.value.reason == "UPLOAD_NOT_FOUND"

        invalid = service.begin_upload("clip.wav", "audio/wav", 4)
        with pytest.raises(ContentServiceError) as bad_format:
            await service.accept_upload(invalid["upload_id"], _chunks(b"nope"))
        assert bad_format.value.reason == "UNSUPPORTED_AUDIO"

        short = service.begin_upload("clip.wav", "audio/wav", 5)
        with pytest.raises(ContentServiceError) as mismatch:
            await service.accept_upload(short["upload_id"], _chunks(b"RIFF"))
        assert mismatch.value.reason == "UPLOAD_SIZE_MISMATCH"
        assert service.list_assets()["total"] == 0
        assert not list((tmp_path / "media" / "uploads").iterdir())
    finally:
        repository.close()


def test_delete_refuses_live_references_then_keeps_a_tombstone(tmp_path):
    repository, service = _service(tmp_path, id_factory=iter(["asset-url"]).__next__)
    try:
        service.create_external_url("https://example.test/audio.mp3", display_name="Audio")
        repository.create_playlist_record("playlist", "Morning")
        repository.add_playlist_item_record("item", "playlist", "asset-url", 0)

        with pytest.raises(ContentServiceError) as referenced:
            service.delete_asset("asset-url")
        assert referenced.value.code == "CONFLICT"
        assert referenced.value.reason == "ASSET_REFERENCED"

        repository.remove_playlist_item_record("item")
        deleted = service.delete_asset("asset-url")
        assert deleted["status"] == "deleted"
        assert repository.get_media_asset("asset-url")["source_value"] == ""
        with pytest.raises(ContentServiceError) as unavailable:
            service.resolve_source("asset-url")
        assert unavailable.value.code == "UNAVAILABLE"
    finally:
        repository.close()
