import asyncio
import io
import json
import zipfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

import pytest
from aiohttp.test_utils import TestClient, TestServer

from miair.app import CastFabric
from miair.config import Config
from miair.dlna.client import DiscoveredDLNATarget
from miair.runtime.models import EventOutcome, IngressProtocol, IngressState
from miair.playback import PlaybackServiceError
from miair.targets import OutputTargetConfig
from miair.web.api import create_web_app


def _build_app(tmp_path):
    targets = {
        "uuid:bedroom": OutputTargetConfig(
            id="uuid:bedroom",
            name="Bedroom",
            location="http://192.168.133.20/device.xml?token=hidden",
            virtual_udn="bedroom-virtual",
        ),
        "uuid:living": OutputTargetConfig(
            id="uuid:living",
            name="Living",
            location="http://192.168.133.21/device.xml",
            virtual_udn="living-virtual",
        ),
    }
    config = Config(
        hostname="127.0.0.1",
        conf_path=str(tmp_path),
        account="private-account",
        password="private-password",
        cookie="userId=private; passToken=private-token",
        mi_did="private-did",
        targets=targets,
        default_target_id="uuid:living",
    )
    app = CastFabric(config)
    for target_id, target in targets.items():
        controller = SimpleNamespace(
            target_id=target_id,
            local_dlna=None,
            play_url=AsyncMock(return_value=True),
            seek=AsyncMock(return_value=True),
            pause=AsyncMock(return_value=True),
            stop=AsyncMock(return_value=True),
            set_volume=AsyncMock(return_value=True),
            get_status=AsyncMock(return_value={"status": 1, "volume": 20}),
        )
        app.suite_registry.register(target, target_id, controller)
        app.suite_registry.set_ingress(
            target_id,
            IngressProtocol.DLNA,
            IngressState.READY,
            handle=object(),
            port=8200,
        )
    return config, app


async def _client(config, app):
    client = TestClient(TestServer(create_web_app(config, app)))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_system_targets_and_suites_match_safe_collection_contract(tmp_path):
    config, app = _build_app(tmp_path)
    client = await _client(config, app)
    contract = json.loads(
        (Path(__file__).parent / "fixtures" / "console_contract.json").read_text(
            encoding="utf-8"
        )
    )
    try:
        system = await (await client.get("/api/v1/system")).json()
        targets = await (await client.get("/api/v1/targets")).json()
        suites = await (await client.get("/api/v1/suites")).json()
    finally:
        await client.close()

    assert set(system) == set(contract["system"])
    assert len(targets["items"]) == 2
    assert set(targets["items"][0]) == set(contract["target"])
    assert len(suites["items"]) == 2
    assert set(suites["items"][0]) == set(contract["suite"])
    payload = json.dumps([system, targets, suites], ensure_ascii=False)
    for forbidden in contract["forbidden"]:
        assert forbidden not in payload
    assert "private-" not in payload
    assert "device.xml" not in payload
    assert targets["items"][0]["online"] is None
    assert all(item["configured"] is True for item in targets["items"])
    assert set(system["suites"]["protocol_health"]) == {"dlna", "airplay", "miplay"}


@pytest.mark.asyncio
async def test_discovered_only_target_is_explicitly_unconfigured(tmp_path):
    config, app = _build_app(tmp_path)

    async def discover():
        return [
            DiscoveredDLNATarget(
                id="uuid:unconfigured",
                name="New speaker",
                location="http://192.168.133.99/device.xml",
                services={"urn:avtransport": "/control"},
            )
        ]

    app.discovery_registry._discover = discover
    await app.discovery_registry.scan()
    client = await _client(config, app)
    try:
        payload = await (await client.get("/api/v1/targets")).json()
    finally:
        await client.close()

    item = next(
        item for item in payload["items"] if item["id"] == "uuid:unconfigured"
    )
    assert item["configured"] is False
    assert item["enabled"] is False
    assert item["online"] is True


@pytest.mark.asyncio
async def test_scan_keeps_single_owner_and_returns_typed_busy_error(tmp_path):
    config, app = _build_app(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    async def discover():
        started.set()
        await release.wait()
        return [
            DiscoveredDLNATarget(
                id="uuid:living",
                name="Living",
                location="http://192.168.133.21/device.xml",
                services={"urn:avtransport": "/control"},
            )
        ]

    app.discovery_registry._discover = discover
    client = await _client(config, app)
    try:
        first = asyncio.create_task(client.post("/api/v1/targets/scan"))
        await started.wait()
        busy = await client.post("/api/v1/targets/scan")
        busy_payload = await busy.json()
        release.set()
        completed = await first
        completed_payload = await completed.json()
    finally:
        await client.close()

    assert busy.status == 409
    assert busy_payload["error"]["code"] == "DISCOVERY_BUSY"
    assert completed.status == 200
    living = next(item for item in completed_payload["items"] if item["id"] == "uuid:living")
    bedroom = next(item for item in completed_payload["items"] if item["id"] == "uuid:bedroom")
    assert living["online"] is True
    assert bedroom["online"] is False


@pytest.mark.asyncio
async def test_target_patch_is_allowlisted_and_toggles_only_requested_suite(tmp_path):
    config, app = _build_app(tmp_path)
    client = await _client(config, app)

    async def set_enabled(target_id, enabled):
        config.get_target(target_id).enabled = enabled
        return app.suite_registry.get(target_id)

    with patch.object(app, "set_target_enabled", AsyncMock(side_effect=set_enabled)) as toggle:
        try:
            rejected = await client.patch(
                "/api/v1/targets/uuid:living",
                json={"location": "http://attacker.invalid", "cookie": "secret"},
            )
            rejected_payload = await rejected.json()
            accepted = await client.patch(
                "/api/v1/targets/uuid:living",
                json={"name": "Main Room", "receiver_alias": "Home Audio", "enabled": False},
            )
            accepted_payload = await accepted.json()
        finally:
            await client.close()

    assert rejected.status == 400
    assert rejected_payload["error"]["code"] == "FIELD_NOT_ALLOWED"
    assert accepted.status == 200
    toggle.assert_awaited_once_with("uuid:living", False)
    assert accepted_payload["item"]["name"] == "Main Room"
    assert accepted_payload["item"]["receiver_alias"] == "Home Audio"
    assert config.get_target("uuid:bedroom").enabled is True


@pytest.mark.asyncio
async def test_enabling_unregistered_target_adds_only_its_suite_to_running_shared_services(tmp_path):
    config, app = _build_app(tmp_path)
    new_target = OutputTargetConfig(
        id="uuid:study",
        name="Study",
        enabled=False,
        virtual_udn="study-virtual",
    )
    config.targets[new_target.id] = new_target
    controller = SimpleNamespace(target_id=new_target.id)
    app.dlna_running = True
    app.speaker_manager.add_target = AsyncMock(
        return_value=(new_target.id, controller)
    )

    async def start_suite(suite):
        app.suite_registry.set_ingress(
            suite.target.id,
            IngressProtocol.DLNA,
            IngressState.READY,
            handle=object(),
            port=8200,
        )

    with (
        patch.object(app, "_start_receiver_suite", AsyncMock(side_effect=start_suite)) as start,
        patch.object(app, "_stop_receiver_suite", AsyncMock()),
    ):
        suite = await app.set_target_enabled(new_target.id, True)

    assert suite.target.id == new_target.id
    assert new_target.enabled is True
    start.assert_awaited_once_with(suite)
    assert app.suite_registry.get("uuid:living") is not None
    assert app.suite_registry.get("uuid:bedroom") is not None
    assert app.suite_registry.get("uuid:living").target.enabled is True


@pytest.mark.asyncio
async def test_target_patch_rolls_back_fields_when_suite_transition_fails(tmp_path):
    config, app = _build_app(tmp_path)
    client = await _client(config, app)
    with patch.object(
        app,
        "set_target_enabled",
        AsyncMock(side_effect=RuntimeError("injected transition failure")),
    ):
        try:
            response = await client.patch(
                "/api/v1/targets/uuid:living",
                json={"name": "Must Roll Back", "enabled": False},
            )
            payload = await response.json()
        finally:
            await client.close()

    assert response.status == 409
    assert payload["error"]["code"] == "SUITE_TRANSITION_FAILED"
    target = config.get_target("uuid:living")
    assert target.name == "Living"
    assert target.enabled is True


@pytest.mark.asyncio
async def test_playback_url_and_controls_use_the_shared_application_service(tmp_path):
    config, app = _build_app(tmp_path)
    controller = app.suite_registry.get("uuid:living").controller
    app.pcm_streams.stop_target = AsyncMock()
    app.media_store.cleanup_target = AsyncMock()
    client = await _client(config, app)
    try:
        played = await client.post(
            "/api/v1/playback/url",
            json={
                "target_id": "UUID:Living",
                "url": "https://media.example.test/notice.mp3?token=secret",
                "media_format": "audio/mpeg",
            },
        )
        status = await client.get("/api/v1/playback/uuid:living")
        paused = await client.post("/api/v1/playback/uuid:living/pause")
        volume = await client.post(
            "/api/v1/playback/uuid:living/volume", json={"volume": 38}
        )
        stopped = await client.post("/api/v1/playback/uuid:living/stop")
        played_payload = await played.json()
        status_payload = await status.json()
        paused_payload = await paused.json()
        volume_payload = await volume.json()
        stopped_payload = await stopped.json()
    finally:
        await client.close()

    assert played.status == 200
    assert played_payload["state"] == "playing"
    assert status_payload == {
        "ok": True,
        "target_id": "uuid:living",
        "state": "playing",
        "volume": 20,
    }
    assert paused_payload["state"] == "paused"
    assert volume_payload["volume"] == 38
    assert stopped_payload["state"] == "stopped"
    controller.play_url.assert_awaited_once_with(
        "https://media.example.test/notice.mp3?token=secret", play_type=2
    )
    app.pcm_streams.stop_target.assert_awaited_once_with(
        "uuid:living", stop_output=False
    )
    app.media_store.cleanup_target.assert_awaited_once_with("uuid:living")


@pytest.mark.asyncio
async def test_play_at_and_seek_current_session_share_http_contract(tmp_path):
    config, app = _build_app(tmp_path)
    controller = app.suite_registry.get("uuid:living").controller
    client = await _client(config, app)
    try:
        played = await client.post(
            "/api/v1/playback/url",
            json={
                "target_id": "uuid:living",
                "url": "https://media.example.test/notice.mp3",
                "start_position_seconds": 90,
            },
        )
        played_payload = await played.json()
        sought = await client.post(
            "/api/v1/playback/uuid:living/seek",
            json={
                "position_seconds": 125,
                "if_session_id": played_payload["session_id"],
            },
        )
        sought_payload = await sought.json()
        stale = await client.post(
            "/api/v1/playback/uuid:living/seek",
            json={"position_seconds": 5, "if_session_id": "stale-session"},
        )
        stale_payload = await stale.json()
    finally:
        await client.close()

    assert played.status == 200
    assert played_payload["position_seconds"] == 90
    assert sought.status == 200
    assert sought_payload["position_seconds"] == 125
    assert sought_payload["session_id"] == played_payload["session_id"]
    assert stale.status == 409
    assert stale_payload["error"]["code"] == "SESSION_CHANGED"
    assert [call.args for call in controller.seek.await_args_list] == [(90,), (125,)]


@pytest.mark.asyncio
async def test_playback_routes_reject_invalid_input_with_stable_safe_errors(tmp_path):
    config, app = _build_app(tmp_path)
    client = await _client(config, app)
    try:
        bad_url = await client.post(
            "/api/v1/playback/url",
            json={"target_id": "uuid:living", "url": "file:///private/audio.mp3"},
        )
        missing = await client.get("/api/v1/playback/uuid:missing")
        bad_volume = await client.post(
            "/api/v1/playback/uuid:living/volume", json={"volume": "loud"}
        )
        bad_url_payload = await bad_url.json()
        missing_payload = await missing.json()
        bad_volume_payload = await bad_volume.json()
    finally:
        await client.close()

    assert bad_url.status == 400
    assert bad_url_payload["error"]["code"] == "INVALID_URL"
    assert missing.status == 404
    assert missing_payload["error"]["code"] == "TARGET_NOT_FOUND"
    assert bad_volume.status == 400
    assert bad_volume_payload["error"]["code"] == "INVALID_VOLUME"
    assert "private" not in json.dumps(bad_volume_payload).lower()


@pytest.mark.asyncio
async def test_agent_stop_releases_local_resources_even_when_output_rejects_stop(tmp_path):
    _config, app = _build_app(tmp_path)
    app.playback_service.stop = AsyncMock(
        side_effect=PlaybackServiceError("TARGET_COMMAND_FAILED", "uuid:living")
    )
    app.pcm_streams.stop_target = AsyncMock()
    app.media_store.cleanup_target = AsyncMock()

    with pytest.raises(PlaybackServiceError):
        await app.stop_agent_playback("uuid:living")

    app.pcm_streams.stop_target.assert_awaited_once_with(
        "uuid:living", stop_output=False
    )
    app.media_store.cleanup_target.assert_awaited_once_with("uuid:living")


@pytest.mark.asyncio
async def test_file_playback_is_one_time_and_renderer_can_fetch_exact_bytes(tmp_path):
    config, app = _build_app(tmp_path)
    controller = app.suite_registry.get("uuid:living").controller
    client = await _client(config, app)
    try:
        created = await client.post(
            "/api/v1/playback/files",
            json={
                "target_id": "uuid:living",
                "filename": "../notice.mp3",
                "content_type": "audio/mpeg",
                "size_bytes": 6,
                "start_position_seconds": 75,
            },
        )
        transaction = await created.json()
        uploaded = await client.put(transaction["upload_path"], data=b"abcdef")
        uploaded_payload = await uploaded.json()
        replayed = await client.put(transaction["upload_path"], data=b"abcdef")
        replayed_payload = await replayed.json()
        media_url = controller.play_url.await_args.args[0]
        fetched = await client.get(urlsplit(media_url).path)
        fetched_body = await fetched.read()
        fetched_again = await client.get(urlsplit(media_url).path)
        fetched_again_body = await fetched_again.read()
        output_events = [
            event
            for event in app.activity_journal.query(target_id="uuid:living")
            if event.type == "agent.output_started"
        ]
    finally:
        await client.close()
        await app.media_store.close()

    assert created.status == 201
    assert uploaded.status == 200
    assert uploaded_payload["state"] == "playing"
    assert uploaded_payload["position_seconds"] == 75
    assert replayed.status == 404
    assert replayed_payload["error"]["code"] == "UPLOAD_NOT_FOUND"
    assert fetched.status == 200
    assert fetched.content_type == "audio/mpeg"
    assert fetched_body == b"abcdef"
    assert fetched_again.status == 200
    assert fetched_again_body == b"abcdef"
    assert len(output_events) == 1
    assert output_events[0].protocol is IngressProtocol.MCP
    assert output_events[0].outcome is EventOutcome.SUCCESS
    assert output_events[0].details == {"media_format": "audio/mpeg"}
    assert "notice.mp3" not in media_url
    controller.seek.assert_awaited_once_with(75)


@pytest.mark.asyncio
async def test_proxy_upload_keeps_agent_https_but_renderer_uses_direct_lan_http(tmp_path):
    config, app = _build_app(tmp_path)
    controller = app.suite_registry.get("uuid:living").controller
    client = await _client(config, app)
    proxy_headers = {
        "Host": "mi-air.internal.wj2015.com",
        "X-Forwarded-Proto": "https",
    }
    try:
        created = await client.post(
            "/api/v1/playback/files",
            headers=proxy_headers,
            json={
                "target_id": "uuid:living",
                "filename": "notice.wav",
                "content_type": "audio/wav",
                "size_bytes": 4,
            },
        )
        transaction = await created.json()
        uploaded = await client.put(
            transaction["upload_path"],
            headers=proxy_headers,
            data=b"wave",
        )
        renderer_url = controller.play_url.await_args.args[0]
    finally:
        await client.close()
        await app.media_store.close()

    assert created.status == 201
    assert transaction["upload_url"].startswith(
        "https://mi-air.internal.wj2015.com/api/v1/playback/files/"
    )
    assert uploaded.status == 200
    assert renderer_url.startswith(
        "http://127.0.0.1:8300/api/v1/playback/media/"
    )


@pytest.mark.asyncio
async def test_proxy_pcm_stream_url_uses_forwarded_wss_origin(tmp_path):
    config, app = _build_app(tmp_path)
    app.pcm_streams = SimpleNamespace(
        create=AsyncMock(
            return_value={
                "ok": True,
                "target_id": "uuid:living",
                "session_id": "session-test",
                "stream_id": "stream-test",
                "stream_path": "/api/v1/playback/streams/stream-test",
                "format": {
                    "sample_format": "s16le",
                    "sample_rate": 48000,
                    "channels": 2,
                },
            }
        ),
        close_all=AsyncMock(),
    )
    client = await _client(config, app)
    try:
        created = await client.post(
            "/api/v1/playback/streams",
            headers={
                "Host": "mi-air.internal.wj2015.com",
                "X-Forwarded-Proto": "https",
            },
            json={
                "target_id": "uuid:living",
                "sample_format": "s16le",
                "sample_rate": 48000,
                "channels": 2,
            },
        )
        payload = await created.json()
    finally:
        await client.close()
        await app.pcm_streams.close_all()

    assert created.status == 201
    assert payload["stream_url"].startswith(
        "wss://mi-air.internal.wj2015.com/api/v1/playback/streams/"
    )


@pytest.mark.asyncio
async def test_pcm_websocket_forwards_binary_frames_and_closes_session(tmp_path):
    config, app = _build_app(tmp_path)
    stream = SimpleNamespace(id="stream-test")
    app.pcm_streams = SimpleNamespace(
        create=AsyncMock(
            return_value={
                "ok": True,
                "target_id": "uuid:living",
                "session_id": "session-test",
                "stream_id": "stream-test",
                "stream_path": "/api/v1/playback/streams/stream-test",
                "format": {
                    "sample_format": "s16le",
                    "sample_rate": 48000,
                    "channels": 2,
                },
            }
        ),
        claim_writer=lambda _stream_id: stream,
        write=AsyncMock(),
        close=AsyncMock(),
    )
    client = await _client(config, app)
    try:
        created = await client.post(
            "/api/v1/playback/streams",
            json={
                "target_id": "uuid:living",
                "sample_format": "s16le",
                "sample_rate": 48000,
                "channels": 2,
            },
        )
        created_payload = await created.json()
        websocket = await client.ws_connect(created_payload["stream_path"])
        await websocket.send_bytes(b"\x01\x02\x03\x04")
        await websocket.close()
    finally:
        await client.close()

    assert created.status == 201
    assert created_payload["stream_url"].startswith("ws://")
    app.pcm_streams.write.assert_awaited_once_with(
        stream, b"\x01\x02\x03\x04"
    )
    app.pcm_streams.close.assert_awaited_once_with("stream-test", failed=False)


@pytest.mark.asyncio
async def test_settings_never_return_credentials_and_reject_unknown_fields(tmp_path):
    config, app = _build_app(tmp_path)
    client = await _client(config, app)
    try:
        response = await client.get("/api/v1/settings")
        settings = await response.json()
        rejected = await client.patch(
            "/api/v1/settings",
            json={"extensions": {"cookie": "replacement"}},
        )
        updated = await client.patch(
            "/api/v1/settings",
            json={
                "identity": {"receiver_prefix": "Whole Home"},
                "network": {"miplay_port": 19000},
            },
        )
        updated_payload = await updated.json()
        invalid = await client.patch(
            "/api/v1/settings",
            json={
                "identity": {"receiver_prefix": "Must Roll Back"},
                "protocols": {"miplay_enabled": "false"},
            },
        )
    finally:
        await client.close()

    serialized = json.dumps(settings)
    assert "private" not in serialized
    assert "cookie" not in serialized
    assert "default_target_id" not in serialized
    assert rejected.status == 400
    assert updated.status == 200
    assert updated_payload["restart_required"] is True
    assert updated_payload["settings"]["identity"]["receiver_prefix"] == "Whole Home"
    assert invalid.status == 400
    assert config.device_name_prefix == "Whole Home"
    assert config.enable_miplay is True


@pytest.mark.asyncio
async def test_sessions_events_and_diagnostics_are_bounded_and_redacted(tmp_path):
    config, app = _build_app(tmp_path)
    session = await app.session_coordinator.begin(
        "uuid:living",
        IngressProtocol.MIPLAY,
        media_format="mpegts",
    )
    event = app.activity_journal.append(
        target_id="uuid:living",
        session_id=session.id,
        protocol=IngressProtocol.MIPLAY,
        type="output.started",
        outcome=EventOutcome.SUCCESS,
        summary_key="activity.output_started",
        details={
            "stream_url": "http://192.168.133.5/live?token=private-token",
            "cookie": "passToken=private-token",
        },
    )
    client = await _client(config, app)
    try:
        sessions = await (await client.get("/api/v1/sessions")).json()
        events = await (await client.get("/api/v1/events?limit=1")).json()
        detail = await (await client.get(f"/api/v1/events/{event.id}")).json()
        diagnostics_response = await client.get("/api/v1/diagnostics/export")
        diagnostics = await diagnostics_response.read()
    finally:
        await client.close()

    contract = json.loads(
        (Path(__file__).parent / "fixtures" / "console_contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(sessions["items"][0]) == set(contract["session"])
    assert set(events["items"][0]) == set(contract["event"])
    assert detail["event"]["id"] == event.id
    assert diagnostics_response.content_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(diagnostics)) as archive:
        combined = "".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
    assert "private-token" not in combined
    assert "private-password" not in combined
    assert "192.168.133.5" not in combined
    assert "192.168.133.20" not in combined
    assert "192.168.133.21" not in combined
    assert "127.0.0.1" not in combined


@pytest.mark.asyncio
async def test_settings_save_failure_restores_every_mutated_runtime_value(tmp_path):
    config, app = _build_app(tmp_path)
    original_prefix = config.device_name_prefix
    original_volume = config.default_volume
    client = await _client(config, app)
    with patch.object(config, "save", side_effect=OSError("disk full")):
        try:
            response = await client.patch(
                "/api/v1/settings",
                json={
                    "identity": {"receiver_prefix": "Must Roll Back"},
                    "playback": {"default_volume": 77},
                },
            )
            payload = await response.json()
        finally:
            await client.close()

    assert response.status == 500
    assert payload["error"]["code"] == "SETTINGS_SAVE_FAILED"
    assert config.device_name_prefix == original_prefix
    assert config.default_volume == original_volume
    assert app.suite_registry.device_name_prefix == original_prefix


@pytest.mark.asyncio
async def test_persistent_media_asset_http_contract_is_searchable_redacted_and_deduplicated(tmp_path):
    config, app = _build_app(tmp_path)
    client = await _client(config, app)
    wav = io.BytesIO()
    with wave.open(wav, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 400)
    body = wav.getvalue()
    try:
        created_url = await client.post(
            "/api/v1/media/assets/url",
            json={
                "url": "https://audio.example.test/show.mp3?token=private",
                "display_name": "Morning show",
                "description": "Daily focus",
                "tags": ["Radio"],
            },
        )
        url_payload = await created_url.json()
        asset_id = url_payload["item"]["id"]
        listed = await client.get("/api/v1/media/assets?query=focus&sort=name")
        list_payload = await listed.json()
        updated = await client.patch(
            f"/api/v1/media/assets/{asset_id}",
            json={"display_name": "First light", "tags": ["Morning"]},
        )
        update_payload = await updated.json()

        transaction = await client.post(
            "/api/v1/media/uploads",
            json={
                "filename": "../../clip.wav",
                "content_type": "application/octet-stream",
                "size_bytes": len(body),
            },
        )
        transaction_payload = await transaction.json()
        uploaded = await client.put(
            urlsplit(transaction_payload["upload_url"]).path,
            data=body,
            headers={"content-type": "application/octet-stream"},
        )
        upload_payload = await uploaded.json()
        fetched = await client.get(
            f"/api/v1/media/assets/{upload_payload['asset']['id']}/content"
        )
        fetched_body = await fetched.read()
    finally:
        await client.close()

    assert created_url.status == 201
    assert listed.status == 200
    assert list_payload["total"] == 1
    assert update_payload["item"]["display_name"] == "First light"
    assert "private" not in json.dumps([url_payload, list_payload, update_payload])
    assert transaction.status == 201
    assert uploaded.status == 201
    assert upload_payload["asset"]["original_filename"] == "clip.wav"
    assert fetched.status == 200
    assert fetched.content_type == "audio/wav"
    assert fetched_body == body


@pytest.mark.asyncio
async def test_persistent_media_http_errors_use_stable_category_reason_and_details(tmp_path):
    config, app = _build_app(tmp_path)
    client = await _client(config, app)
    try:
        invalid = await client.post(
            "/api/v1/media/assets/url",
            json={"url": "file:///private/audio", "display_name": "Private"},
        )
        missing = await client.get("/api/v1/media/assets/missing")
        invalid_payload = await invalid.json()
        missing_payload = await missing.json()
    finally:
        await client.close()

    assert invalid.status == 400
    assert invalid_payload["error"]["code"] == "INVALID_INPUT"
    assert invalid_payload["error"]["details"]["reason"] == "INVALID_URL"
    assert missing.status == 404
    assert missing_payload["error"]["code"] == "NOT_FOUND"
    assert missing_payload["error"]["details"]["reason"] == "ASSET_NOT_FOUND"
