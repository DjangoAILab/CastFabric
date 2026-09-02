"""Privacy-safe collection API for the CastFabric Runtime v2 console."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web

from miair.const import VERSION
from miair.identity import PRODUCT_NAME, normalize_device_prefix
from miair.playback import FilePlaybackError, PcmStreamError, PlaybackServiceError
from miair.runtime.discovery import DiscoveryBusyError
from miair.runtime.models import (
    EventOutcome,
    IngressProtocol,
    RECEIVER_PROTOCOLS,
    SessionState,
)
from miair.runtime.redaction import project_location_host, redact_network_addresses
from miair.targets import OutputTargetConfig, normalize_target_id
from miair.web.origin import request_public_origin, speaker_media_origin


def _redact_diagnostic(value):
    if isinstance(value, dict):
        return {key: _redact_diagnostic(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_diagnostic(item) for item in value]
    if isinstance(value, str):
        return redact_network_addresses(value)
    return value


def _error(
    code: str,
    message_key: str,
    *,
    status: int,
    details: dict[str, Any] | None = None,
) -> web.Response:
    return web.json_response(
        {
            "error": {
                "code": code,
                "message_key": message_key,
                "details": details or {},
            }
        },
        status=status,
    )


def _observation_state(app, target_id: str):
    observations = app.discovery_registry.snapshot()
    observation = observations.get(target_id)
    observed_at = app.discovery_registry.observed_at
    online = None if observed_at is None else observation is not None
    capabilities = tuple(sorted(observation.services)) if observation else ()
    return observation, online, observed_at, capabilities


def _sync_suite_observations(app) -> None:
    for suite in app.suite_registry.values():
        _, online, observed_at, capabilities = _observation_state(
            app,
            suite.target.id,
        )
        suite.update_observation(
            online=online,
            observed_at=observed_at,
            capabilities=capabilities,
        )


def _target_item(config, app, target_id: str) -> dict[str, Any] | None:
    target = config.get_target(target_id)
    observation, online, observed_at, capabilities = _observation_state(
        app,
        target_id,
    )
    if target is None and observation is None:
        return None
    if target is None:
        name = observation.name
        kind = "dlna"
        enabled = False
        alias = config.get_device_name(name)
        location = observation.location
    else:
        name = target.name
        kind = target.kind
        enabled = target.enabled
        alias = target.get_receiver_alias(config.device_name_prefix)
        location = target.location
    suite = app.suite_registry.get(target_id)
    return {
        "id": target_id,
        "kind": kind,
        "name": name,
        "receiver_alias": alias,
        "location_host": project_location_host(location),
        "configured": target is not None,
        "enabled": enabled,
        "online": online,
        "observed_at": observed_at.isoformat() if observed_at else None,
        "capabilities": list(capabilities),
        "suite_health": suite.health if suite else ("disabled" if not enabled else "unavailable"),
    }


def _target_items(config, app) -> list[dict[str, Any]]:
    target_ids = set(config.targets) | set(app.discovery_registry.snapshot())
    result = [_target_item(config, app, target_id) for target_id in sorted(target_ids)]
    return [item for item in result if item is not None]


def _system_payload(config, app) -> dict[str, Any]:
    _sync_suite_observations(app)
    suites = app.suite_registry.snapshots()
    sessions = app.session_coordinator.current_all()
    enabled = [suite for suite in suites if suite.target.enabled]
    attention = [suite for suite in enabled if suite.health != "healthy"]
    protocol_health = {}
    for protocol in RECEIVER_PROTOCOLS:
        states = [
            ingress.state.value
            for suite in enabled
            for ingress in suite.ingress
            if ingress.protocol is protocol
        ]
        protocol_health[protocol.value] = {
            "ready": sum(state in {"ready", "active"} for state in states),
            "total": len(enabled),
        }
    if not enabled:
        health = "idle"
    elif attention:
        health = "degraded"
    else:
        health = "healthy"
    xiaomi_state = (
        "disabled"
        if not config.enable_xiaomi_extension
        else "authenticated"
        if app.auth.is_logged_in()
        else "unavailable"
    )
    return {
        "product": PRODUCT_NAME,
        "version": VERSION,
        "health": health,
        "hostname": config.hostname,
        "receiver_prefix": config.device_name_prefix,
        "ports": {
            "web": config.web_port,
            "dlna": config.dlna_port,
            "miplay_base": config.miplay_port,
        },
        "targets": {
            "count": len(config.targets),
            "enabled_count": len(enabled),
            "online_count": sum(item["online"] is True for item in _target_items(config, app)),
        },
        "suites": {
            "enabled_count": len(enabled),
            "ready_count": sum(suite.health == "healthy" for suite in enabled),
            "attention_count": len(attention),
            "disabled_count": sum(not target.enabled for target in config.targets.values()),
            "protocol_health": protocol_health,
        },
        "sessions": {
            "active_count": len(sessions),
            "playing_count": sum(session.state is SessionState.PLAYING for session in sessions),
        },
        "discovery": app.discovery_registry.status(),
        "observability": {
            "state": "degraded" if app.activity_journal.degraded else "ready"
        },
        "extensions": {
            "xiaomi": {
                "enabled": config.enable_xiaomi_extension,
                "auth_state": xiaomi_state,
            }
        },
    }


def _settings_payload(config, app) -> dict[str, Any]:
    return {
        "identity": {"receiver_prefix": config.device_name_prefix},
        "playback": {
            "default_volume": config.default_volume,
            "follow_device_volume": config.follow_device_volume,
            "auto_resume_on_interrupt": config.auto_resume_on_interrupt,
            "resume_delay_seconds": config.resume_delay_seconds,
        },
        "network": {
            "hostname": config.hostname,
            "web_port": config.web_port,
            "dlna_port": config.dlna_port,
            "miplay_port": config.miplay_port,
        },
        "protocols": {"miplay_enabled": config.enable_miplay},
        "extensions": {
            "xiaomi_enabled": config.enable_xiaomi_extension,
            "xiaomi_auth_state": (
                "disabled"
                if not config.enable_xiaomi_extension
                else "authenticated"
                if app.auth.is_logged_in()
                else "unavailable"
            ),
        },
        "system": {
            "log_level": "debug" if config.verbose else "info",
            "version": VERSION,
        },
    }


async def _json_object(request: web.Request) -> dict[str, Any] | web.Response:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _error("INVALID_JSON", "error.invalid_json", status=400)
    if not isinstance(payload, dict):
        return _error("INVALID_BODY", "error.invalid_body", status=400)
    return payload


def setup_api_v1_routes(web_app: web.Application, config, app) -> None:
    def playback_error(exc: PlaybackServiceError) -> web.Response:
        status = {
            "TARGET_NOT_FOUND": 404,
            "TARGET_DISABLED": 409,
            "TARGET_COMMAND_FAILED": 502,
        }.get(exc.code, 500)
        return _error(
            exc.code,
            f"error.{exc.code.lower()}",
            status=status,
            details={"target_id": exc.target_id},
        )

    async def get_system(request):
        return web.json_response(_system_payload(config, app))

    async def get_targets(request):
        return web.json_response(
            {
                "items": _target_items(config, app),
                "discovery": app.discovery_registry.status(),
            }
        )

    async def scan_targets(request):
        try:
            await app.scan_output_targets()
        except DiscoveryBusyError:
            return _error(
                "DISCOVERY_BUSY",
                "error.discovery_busy",
                status=409,
            )
        except Exception:
            return _error(
                app.discovery_registry.error_code or "DISCOVERY_FAILED",
                "error.discovery_failed",
                status=503,
            )
        _sync_suite_observations(app)
        return web.json_response(
            {
                "items": _target_items(config, app),
                "discovery": app.discovery_registry.status(),
            }
        )

    async def patch_target(request):
        payload = await _json_object(request)
        if isinstance(payload, web.Response):
            return payload
        allowed = {"name", "receiver_alias", "enabled"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            return _error(
                "FIELD_NOT_ALLOWED",
                "error.field_not_allowed",
                status=400,
                details={"fields": unknown},
            )
        target_id = normalize_target_id(request.match_info["target_id"])
        target = config.get_target(target_id)
        created = False
        if target is None:
            observation = app.discovery_registry.snapshot().get(target_id)
            if observation is None:
                return _error("TARGET_NOT_FOUND", "error.target_not_found", status=404)
            target = OutputTargetConfig(
                id=observation.id,
                kind="dlna",
                name=observation.name,
                location=observation.location,
                udn=observation.id,
                enabled=False,
            )
            config.targets[target.id] = target
            created = True
        old = (target.name, target.receiver_alias, target.enabled)
        try:
            proposed_name = target.name
            proposed_alias = target.receiver_alias
            if "name" in payload:
                name = str(payload["name"]).strip()
                if not name or len(name) > 80:
                    raise ValueError("INVALID_TARGET_NAME")
                proposed_name = name
            if "receiver_alias" in payload:
                alias = str(payload["receiver_alias"]).strip()
                if len(alias) > 80:
                    raise ValueError("INVALID_RECEIVER_ALIAS")
                proposed_alias = alias
            requested_enabled = target.enabled
            if "enabled" in payload:
                if not isinstance(payload["enabled"], bool):
                    raise ValueError("INVALID_ENABLED_VALUE")
                requested_enabled = payload["enabled"]

            # Disable using the currently advertised identity. Enable using the
            # proposed identity so a newly started suite never needs a second
            # restart merely to pick up its name.
            if target.enabled and not requested_enabled:
                await app.set_target_enabled(target.id, False)
                target.name = proposed_name
                target.receiver_alias = proposed_alias
            else:
                target.name = proposed_name
                target.receiver_alias = proposed_alias
                if not target.enabled and requested_enabled:
                    await app.set_target_enabled(target.id, True)
            config.save()
        except ValueError as exc:
            target.name, target.receiver_alias, target.enabled = old
            if created:
                config.targets.pop(target.id, None)
            return _error(str(exc), "error.invalid_target", status=400)
        except Exception as exc:
            rollback_failed = False
            current_enabled = target.enabled
            target.name, target.receiver_alias = old[0], old[1]
            if current_enabled != old[2]:
                try:
                    await app.set_target_enabled(target.id, old[2])
                except Exception:
                    rollback_failed = True
            target.enabled = old[2]
            if created:
                config.targets.pop(target.id, None)
            try:
                config.save()
            except OSError:
                rollback_failed = True
            return _error(
                "SUITE_ROLLBACK_FAILED"
                if rollback_failed
                else getattr(exc, "code", "SUITE_TRANSITION_FAILED"),
                "error.suite_transition_failed",
                status=500 if rollback_failed else 409,
            )
        item = _target_item(config, app, target.id)
        return web.json_response(
            {
                "item": item,
                "restart_required": bool(
                    old[2]
                    and target.enabled
                    and ({"name", "receiver_alias"} & set(payload))
                ),
            }
        )

    async def get_suites(request):
        _sync_suite_observations(app)
        return web.json_response(
            {"items": [suite.to_dict() for suite in app.suite_registry.snapshots()]}
        )

    async def play_url(request):
        payload = await _json_object(request)
        if isinstance(payload, web.Response):
            return payload
        allowed = {"target_id", "url", "media_format"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            return _error(
                "FIELD_NOT_ALLOWED",
                "error.field_not_allowed",
                status=400,
                details={"fields": unknown},
            )
        target_id = normalize_target_id(payload.get("target_id"))
        url = payload.get("url")
        if not target_id:
            return _error("INVALID_TARGET_ID", "error.invalid_target_id", status=400)
        if not isinstance(url, str):
            return _error("INVALID_URL", "error.invalid_url", status=400)
        parsed = urlsplit(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return _error("INVALID_URL", "error.invalid_url", status=400)
        media_format = payload.get("media_format")
        if media_format is not None and not isinstance(media_format, str):
            return _error(
                "INVALID_MEDIA_FORMAT",
                "error.invalid_media_format",
                status=400,
            )
        try:
            result = await app.playback_service.play_url(
                target_id,
                url.strip(),
                media_format=media_format.strip() if media_format else None,
            )
        except PlaybackServiceError as exc:
            return playback_error(exc)
        return web.json_response(result)

    async def playback_status(request):
        try:
            result = await app.playback_service.get_status(
                request.match_info["target_id"]
            )
        except PlaybackServiceError as exc:
            return playback_error(exc)
        return web.json_response(result)

    async def pause_playback(request):
        try:
            result = await app.playback_service.pause(request.match_info["target_id"])
        except PlaybackServiceError as exc:
            return playback_error(exc)
        return web.json_response(result)

    async def stop_playback(request):
        try:
            result = await app.stop_agent_playback(request.match_info["target_id"])
        except PlaybackServiceError as exc:
            return playback_error(exc)
        return web.json_response(result)

    async def set_playback_volume(request):
        payload = await _json_object(request)
        if isinstance(payload, web.Response):
            return payload
        if set(payload) != {"volume"} or isinstance(payload.get("volume"), bool):
            return _error("INVALID_VOLUME", "error.invalid_volume", status=400)
        try:
            volume = int(payload["volume"])
        except (TypeError, ValueError):
            return _error("INVALID_VOLUME", "error.invalid_volume", status=400)
        if volume < 0 or volume > 100:
            return _error("INVALID_VOLUME", "error.invalid_volume", status=400)
        try:
            result = await app.playback_service.set_volume(
                request.match_info["target_id"],
                volume,
            )
        except PlaybackServiceError as exc:
            return playback_error(exc)
        return web.json_response(result)

    async def create_file_upload(request):
        payload = await _json_object(request)
        if isinstance(payload, web.Response):
            return payload
        if set(payload) != {"target_id", "filename", "content_type", "size_bytes"}:
            return _error("INVALID_FILE", "error.invalid_file", status=400)
        try:
            transaction = app.media_store.create_upload(
                payload["target_id"],
                payload["filename"],
                payload["content_type"],
                payload["size_bytes"],
            )
        except PlaybackServiceError as exc:
            return playback_error(exc)
        except FilePlaybackError as exc:
            return _error(exc.code, f"error.{exc.code.lower()}", status=400)
        transaction["upload_url"] = (
            request_public_origin(request) + transaction["upload_path"]
        )
        return web.json_response(transaction, status=201)

    async def upload_file(request):
        upload_id = request.match_info["upload_id"]
        try:
            result = await app.media_store.accept_upload(
                upload_id,
                request.content.iter_chunked(64 * 1024),
                origin=speaker_media_origin(config),
            )
        except FilePlaybackError as exc:
            status = 404 if exc.code in {"UPLOAD_NOT_FOUND", "MEDIA_NOT_FOUND"} else 400
            return _error(exc.code, f"error.{exc.code.lower()}", status=status)
        except PlaybackServiceError as exc:
            return playback_error(exc)
        return web.json_response(result)

    async def get_playback_media(request):
        try:
            media, first_pull = app.media_store.confirm_pull(
                request.match_info["media_token"]
            )
        except FilePlaybackError as exc:
            return _error(exc.code, f"error.{exc.code.lower()}", status=404)
        if first_pull:
            session = app.session_coordinator.current(media.target_id)
            app.activity_journal.append(
                target_id=media.target_id,
                session_id=session.id if session else None,
                protocol=IngressProtocol.MCP,
                type="agent.output_started",
                outcome=EventOutcome.SUCCESS,
                summary_key="activity.agent_output_started",
                details={"media_format": media.content_type},
            )
        response = web.FileResponse(media.path)
        response.content_type = media.content_type
        return response

    async def create_pcm_stream(request):
        payload = await _json_object(request)
        if isinstance(payload, web.Response):
            return payload
        if set(payload) != {
            "target_id",
            "sample_format",
            "sample_rate",
            "channels",
        }:
            return _error(
                "UNSUPPORTED_PCM_FORMAT",
                "error.unsupported_pcm_format",
                status=400,
            )
        try:
            result = await app.pcm_streams.create(
                payload["target_id"],
                sample_format=payload["sample_format"],
                sample_rate=payload["sample_rate"],
                channels=payload["channels"],
            )
        except PlaybackServiceError as exc:
            return playback_error(exc)
        except PcmStreamError as exc:
            return _error(exc.code, f"error.{exc.code.lower()}", status=400)
        public_origin = request_public_origin(request)
        result["stream_url"] = (
            "ws" + public_origin[4:] + result["stream_path"]
        )
        return web.json_response(result, status=201)

    async def write_pcm_stream(request):
        stream_id = request.match_info["stream_id"]
        try:
            stream = app.pcm_streams.claim_writer(stream_id)
        except PcmStreamError as exc:
            status = 404 if exc.code == "STREAM_NOT_FOUND" else 409
            return _error(exc.code, f"error.{exc.code.lower()}", status=status)
        websocket = web.WebSocketResponse()
        await websocket.prepare(request)
        failed = False
        try:
            async for message in websocket:
                if message.type is web.WSMsgType.BINARY:
                    await app.pcm_streams.write(stream, message.data)
                elif message.type is web.WSMsgType.TEXT:
                    failed = True
                    await websocket.close(
                        code=web.WSCloseCode.UNSUPPORTED_DATA,
                        message=b"binary PCM frames required",
                    )
                    break
                elif message.type is web.WSMsgType.ERROR:
                    failed = True
                    break
        except Exception:
            failed = True
            await websocket.close(code=web.WSCloseCode.INTERNAL_ERROR)
        finally:
            await app.pcm_streams.close(stream_id, failed=failed)
        return websocket

    async def get_sessions(request):
        include_recent = request.query.get("include_recent", "false").lower() == "true"
        try:
            limit = int(request.query.get("limit", "100"))
        except ValueError:
            return _error("INVALID_LIMIT", "error.invalid_limit", status=400)
        return web.json_response(
            {
                "items": [
                    session.to_dict()
                    for session in app.session_coordinator.query(
                        include_recent=include_recent,
                        limit=limit,
                    )
                ]
            }
        )

    async def get_events(request):
        try:
            protocol = (
                IngressProtocol(request.query["protocol"])
                if request.query.get("protocol")
                else None
            )
            outcome = (
                EventOutcome(request.query["outcome"])
                if request.query.get("outcome")
                else None
            )
            limit = int(request.query.get("limit", "100"))
        except (ValueError, KeyError):
            return _error("INVALID_FILTER", "error.invalid_filter", status=400)
        events = app.activity_journal.query(
            target_id=request.query.get("target_id"),
            protocol=protocol,
            outcome=outcome,
            limit=limit,
            cursor=request.query.get("cursor"),
        )
        return web.json_response(
            {
                "items": [event.to_dict() for event in events],
                "next_cursor": events[-1].id if len(events) == max(1, min(limit, 500)) else None,
                "degraded": app.activity_journal.degraded,
            }
        )

    async def get_event(request):
        event = app.activity_journal.get(request.match_info["event_id"])
        if event is None:
            return _error("EVENT_NOT_FOUND", "error.event_not_found", status=404)
        sessions = app.session_coordinator.query(include_recent=True, limit=200)
        session = next(
            (item for item in sessions if item.id == event.session_id),
            None,
        )
        return web.json_response(
            {
                "event": event.to_dict(),
                "session": session.to_dict() if session else None,
                "target": _target_item(config, app, event.target_id),
            }
        )

    async def get_settings(request):
        return web.json_response(_settings_payload(config, app))

    async def patch_settings(request):
        payload = await _json_object(request)
        if isinstance(payload, web.Response):
            return payload
        allowed = {
            "identity": {"receiver_prefix"},
            "playback": {
                "default_volume",
                "follow_device_volume",
                "auto_resume_on_interrupt",
                "resume_delay_seconds",
            },
            "network": {"web_port", "dlna_port", "miplay_port"},
            "protocols": {"miplay_enabled"},
            "extensions": {"xiaomi_enabled"},
            "system": {"log_level"},
        }
        for section, values in payload.items():
            if section not in allowed or not isinstance(values, dict):
                return _error("FIELD_NOT_ALLOWED", "error.field_not_allowed", status=400)
            unknown = set(values) - allowed[section]
            if unknown:
                return _error(
                    "FIELD_NOT_ALLOWED",
                    "error.field_not_allowed",
                    status=400,
                    details={"fields": sorted(f"{section}.{key}" for key in unknown)},
                )
        restart_required = False
        old_values = {
            "device_name_prefix": config.device_name_prefix,
            "miplay_name": config.miplay_name,
            "default_volume": config.default_volume,
            "follow_device_volume": config.follow_device_volume,
            "auto_resume_on_interrupt": config.auto_resume_on_interrupt,
            "resume_delay_seconds": config.resume_delay_seconds,
            "web_port": config.web_port,
            "dlna_port": config.dlna_port,
            "miplay_port": config.miplay_port,
            "enable_miplay": config.enable_miplay,
            "enable_xiaomi_extension": config.enable_xiaomi_extension,
            "verbose": config.verbose,
        }
        try:
            identity = payload.get("identity", {})
            if "receiver_prefix" in identity:
                if not isinstance(identity["receiver_prefix"], str):
                    raise ValueError
                config.device_name_prefix = normalize_device_prefix(
                    identity["receiver_prefix"]
                )
                config.miplay_name = config.device_name_prefix
                app.suite_registry.device_name_prefix = config.device_name_prefix
                restart_required = True
            playback = payload.get("playback", {})
            if "default_volume" in playback:
                if isinstance(playback["default_volume"], bool):
                    raise ValueError
                config.default_volume = max(1, min(100, int(playback["default_volume"])))
            if "follow_device_volume" in playback:
                if not isinstance(playback["follow_device_volume"], bool):
                    raise ValueError
                config.follow_device_volume = playback["follow_device_volume"]
            if "auto_resume_on_interrupt" in playback:
                if not isinstance(playback["auto_resume_on_interrupt"], bool):
                    raise ValueError
                config.auto_resume_on_interrupt = playback["auto_resume_on_interrupt"]
            if "resume_delay_seconds" in playback:
                if isinstance(playback["resume_delay_seconds"], bool):
                    raise ValueError
                config.resume_delay_seconds = max(1, min(15, int(playback["resume_delay_seconds"])))
            network = payload.get("network", {})
            if "web_port" in network:
                if isinstance(network["web_port"], bool):
                    raise ValueError
                config.web_port = max(1, min(65535, int(network["web_port"])))
                restart_required = True
            if "dlna_port" in network:
                if isinstance(network["dlna_port"], bool):
                    raise ValueError
                config.dlna_port = max(1, min(65535, int(network["dlna_port"])))
                restart_required = True
            if "miplay_port" in network:
                if isinstance(network["miplay_port"], bool):
                    raise ValueError
                config.miplay_port = max(0, min(65535, int(network["miplay_port"])))
                restart_required = True
            protocols = payload.get("protocols", {})
            if "miplay_enabled" in protocols:
                if not isinstance(protocols["miplay_enabled"], bool):
                    raise ValueError
                config.enable_miplay = protocols["miplay_enabled"]
                restart_required = True
            extensions = payload.get("extensions", {})
            if "xiaomi_enabled" in extensions:
                if not isinstance(extensions["xiaomi_enabled"], bool):
                    raise ValueError
                config.enable_xiaomi_extension = extensions["xiaomi_enabled"]
                restart_required = True
            system = payload.get("system", {})
            if "log_level" in system:
                if not isinstance(system["log_level"], str):
                    raise ValueError
                level = system["log_level"].lower()
                if level not in {"info", "debug"}:
                    raise ValueError
                config.verbose = level == "debug"
            config.save()
        except (TypeError, ValueError):
            for key, value in old_values.items():
                setattr(config, key, value)
            app.suite_registry.device_name_prefix = config.device_name_prefix
            return _error("INVALID_SETTING", "error.invalid_setting", status=400)
        except OSError:
            for key, value in old_values.items():
                setattr(config, key, value)
            app.suite_registry.device_name_prefix = config.device_name_prefix
            return _error(
                "SETTINGS_SAVE_FAILED",
                "error.settings_save_failed",
                status=500,
            )
        return web.json_response(
            {
                "settings": _settings_payload(config, app),
                "restart_required": restart_required,
            }
        )

    async def export_diagnostics(request):
        payloads = {
            "manifest.json": {
                "schema": 1,
                "system": _system_payload(config, app),
            },
            "targets.json": {"items": _target_items(config, app)},
            "suites.json": {
                "items": [suite.to_dict() for suite in app.suite_registry.snapshots()]
            },
            "events.json": {
                "items": [
                    event.to_dict()
                    for event in app.activity_journal.query(limit=200)
                ]
            },
        }
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, payload in payloads.items():
                archive.writestr(
                    filename,
                    json.dumps(
                        _redact_diagnostic(payload),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        return web.Response(
            body=stream.getvalue(),
            content_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="castfabric-diagnostics.zip"'
            },
        )

    web_app.router.add_get("/api/v1/system", get_system)
    web_app.router.add_get("/api/v1/targets", get_targets)
    web_app.router.add_post("/api/v1/targets/scan", scan_targets)
    web_app.router.add_patch("/api/v1/targets/{target_id:.+}", patch_target)
    web_app.router.add_get("/api/v1/suites", get_suites)
    web_app.router.add_post("/api/v1/playback/url", play_url)
    web_app.router.add_get("/api/v1/playback/{target_id:.+}", playback_status)
    web_app.router.add_post(
        "/api/v1/playback/{target_id:.+}/pause", pause_playback
    )
    web_app.router.add_post(
        "/api/v1/playback/{target_id:.+}/stop", stop_playback
    )
    web_app.router.add_post(
        "/api/v1/playback/{target_id:.+}/volume", set_playback_volume
    )
    web_app.router.add_post("/api/v1/playback/files", create_file_upload)
    web_app.router.add_put(
        "/api/v1/playback/files/{upload_id}", upload_file
    )
    web_app.router.add_get(
        "/api/v1/playback/media/{media_token}", get_playback_media
    )
    web_app.router.add_post("/api/v1/playback/streams", create_pcm_stream)
    web_app.router.add_get(
        "/api/v1/playback/streams/{stream_id}", write_pcm_stream
    )
    web_app.router.add_get("/api/v1/sessions", get_sessions)
    web_app.router.add_get("/api/v1/events", get_events)
    web_app.router.add_get("/api/v1/events/{event_id}", get_event)
    web_app.router.add_get("/api/v1/settings", get_settings)
    web_app.router.add_patch("/api/v1/settings", patch_settings)
    web_app.router.add_get("/api/v1/diagnostics/export", export_diagnostics)
