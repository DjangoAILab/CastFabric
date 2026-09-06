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
async def test_reupload_deleted_bytes_creates_new_asset_without_reviving_history(tmp_path):
    payload = _wav_bytes()
    repository, service = _service(tmp_path)
    try:
        ticket = service.begin_upload("original.wav", "audio/wav", len(payload))
        original = (await service.accept_upload(ticket["upload_id"], _chunks(payload)))["asset"]
        old_hash = repository.get_media_asset(original["id"])["content_hash"]
        service.delete_asset(original["id"])
        # Exercise legacy tombstones too: they still own the unique hash.
        assert repository.find_media_asset_by_hash(old_hash)["status"] == "deleted"
        ticket = service.begin_upload("new-name.wav", "audio/wav", len(payload))
        result = await service.accept_upload(ticket["upload_id"], _chunks(payload))
        assert result["deduplicated"] is False
        assert result["asset"]["id"] != original["id"]
        assert result["asset"]["original_filename"] == "new-name.wav"
        assert repository.get_media_asset(original["id"])["status"] == "deleted"
        assert repository.find_media_asset_by_hash(old_hash)["id"] == result["asset"]["id"]
        path, _ = service.resolve_managed_file(result["asset"]["id"])
        assert path.read_bytes() == payload
        ticket = service.begin_upload("copy.wav", "audio/wav", len(payload))
        duplicate = await service.accept_upload(ticket["upload_id"], _chunks(payload))
        assert duplicate["deduplicated"] is True
        assert duplicate["asset"]["id"] == result["asset"]["id"]
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


def _mp3_bytes():
    import av

    output = io.BytesIO()
    with av.open(output, 'w', format='mp3') as container:
        stream = container.add_stream('libmp3lame', rate=44100)
        stream.layout = 'mono'
        frame = av.AudioFrame(format='s16p', layout='mono', samples=44100)
        frame.sample_rate = 44100
        for plane in frame.planes:
            plane.update(bytes(plane.buffer_size))
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return output.getvalue()


@pytest.mark.asyncio
async def test_mp3_upload_extracts_duration_without_filename_extension(tmp_path):
    repository, service = _service(tmp_path)
    try:
        payload = _mp3_bytes()
        ticket = service.begin_upload('recording.mp3', 'audio/mpeg', len(payload))
        asset = (await service.accept_upload(ticket['upload_id'], _chunks(payload)))['asset']
        assert asset['duration_seconds'] == pytest.approx(1, abs=0.15)
    finally:
        repository.close()


def test_duration_backfill_is_local_idempotent_and_preserves_metadata(tmp_path):
    repository, service = _service(tmp_path)
    try:
        path = service.blob_directory / 'old-mp3'
        path.write_bytes(_mp3_bytes())
        original = repository.create_media_asset(dict(
            id='old', source_kind='managed_file', display_name='Original title',
            source_value='blobs/old-mp3', content_type='audio/mpeg', description='Credit',
        ))
        service.create_external_url('https://example.invalid/not-fetched.mp3', display_name='URL')
        missing = repository.create_media_asset(dict(
            id='missing', source_kind='managed_file', display_name='Missing', source_value='blobs/missing',
        ))
        assert service.backfill_durations() == 1
        updated = repository.get_media_asset('old')
        assert updated['duration_seconds'] == pytest.approx(1, abs=0.15)
        assert {k: v for k, v in updated.items() if k != 'duration_seconds'} == {
            k: v for k, v in original.items() if k != 'duration_seconds'
        }
        assert repository.get_media_asset('missing') == missing
        assert service.backfill_durations() == 0
        assert repository.business_tables() == {
            'media_assets', 'playlists', 'playlist_items', 'playback_runs', 'media_sessions', 'activity_events'
        }
    finally:
        repository.close()


def test_duration_probe_leaves_invalid_audio_unknown(tmp_path):
    path = tmp_path / 'invalid'
    path.write_bytes(b'ID3invalid')
    assert MediaAssetService._duration(path, 'mp3') is None
    assert MediaAssetService._duration(path, 'unsupported') is None
