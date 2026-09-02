"""Official MCP SDK tools mounted into the existing aiohttp listener."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any
from urllib.parse import urlsplit

from aiohttp import web
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from miair.playback import FilePlaybackError, PcmStreamError, PlaybackServiceError
from miair.targets import OutputTargetConfig, normalize_target_id
from miair.web.origin import request_public_origin


class EmbeddedMcpEndpoint:
    """Translate one aiohttp request into the official SDK's ASGI endpoint."""

    def __init__(self, app, config):
        self.app = app
        self.config = config
        self._request_origin: ContextVar[str | None] = ContextVar(
            "castfabric_mcp_request_origin",
            default=None,
        )
        self.server = MCPServer(
            name="CastFabric",
            version="1",
            instructions=(
                "Call list_outputs before selecting a target_id. "
                "Never guess an output identifier."
            ),
        )
        self._register_tools()
        self.asgi_app = self.server.streamable_http_app(
            streamable_http_path="/",
            json_response=True,
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
            ),
        )

    def _public_origin(self) -> str:
        return self._request_origin.get() or (
            f"http://{self.config.hostname}:{self.config.web_port}"
        )

    @staticmethod
    def _tool_error(exc: Exception) -> ToolError:
        code = getattr(exc, "code", "CASTFABRIC_ERROR")
        return ToolError(str(code))

    def _register_tools(self) -> None:
        server = self.server

        @server.tool(
            description="Return the safe CastFabric system status.",
            structured_output=True,
        )
        async def get_system_status() -> dict[str, Any]:
            from miair.web.api_v1 import _system_payload

            return _system_payload(self.config, self.app)

        @server.tool(
            description=(
                "List configured and recently discovered output speakers. "
                "Call this before any tool requiring target_id."
            ),
            structured_output=True,
        )
        async def list_outputs() -> dict[str, Any]:
            from miair.web.api_v1 import _target_items

            return {
                "items": _target_items(self.config, self.app),
                "discovery": self.app.discovery_registry.status(),
            }

        @server.tool(
            description="Scan the LAN for DLNA output speakers.",
            structured_output=True,
        )
        async def scan_outputs() -> dict[str, Any]:
            from miair.web.api_v1 import _target_items

            try:
                await self.app.scan_output_targets()
            except Exception as exc:
                raise self._tool_error(exc) from exc
            return {
                "items": _target_items(self.config, self.app),
                "discovery": self.app.discovery_registry.status(),
            }

        @server.tool(
            description=(
                "Add or update one discovered output. Use target_id returned "
                "by list_outputs or scan_outputs."
            ),
            structured_output=True,
        )
        async def update_output(
            target_id: str,
            name: str | None = None,
            receiver_alias: str | None = None,
            enabled: bool | None = None,
        ) -> dict[str, Any]:
            from miair.web.api_v1 import _target_item

            normalized = normalize_target_id(target_id)
            target = self.config.get_target(normalized)
            if target is None:
                observation = self.app.discovery_registry.snapshot().get(normalized)
                if observation is None:
                    raise ToolError("TARGET_NOT_FOUND")
                target = OutputTargetConfig(
                    id=observation.id,
                    kind="dlna",
                    name=observation.name,
                    location=observation.location,
                    udn=observation.id,
                    enabled=False,
                )
                self.config.targets[target.id] = target
            if name is not None:
                clean_name = str(name).strip()
                if not clean_name or len(clean_name) > 80:
                    raise ToolError("INVALID_TARGET_NAME")
                target.name = clean_name
            if receiver_alias is not None:
                clean_alias = str(receiver_alias).strip()
                if len(clean_alias) > 80:
                    raise ToolError("INVALID_RECEIVER_ALIAS")
                target.receiver_alias = clean_alias
            if enabled is not None and target.enabled != enabled:
                try:
                    await self.app.set_target_enabled(target.id, enabled)
                except Exception as exc:
                    raise self._tool_error(exc) from exc
            self.config.save()
            return {"item": _target_item(self.config, self.app, target.id)}

        @server.tool(
            description=(
                "Play an HTTP or HTTPS audio URL on target_id. Call "
                "list_outputs first when the exact target_id is unknown."
            ),
            structured_output=True,
        )
        async def play_url(
            target_id: str,
            url: str,
            media_format: str | None = None,
            start_position_seconds: int = 0,
        ) -> dict[str, Any]:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ToolError("INVALID_URL")
            try:
                return await self.app.playback_service.play_url(
                    target_id,
                    url,
                    media_format=media_format,
                    start_position_seconds=start_position_seconds,
                )
            except PlaybackServiceError as exc:
                raise self._tool_error(exc) from exc

        @server.tool(
            description=(
                "Create a one-time upload for an Agent-local audio file. "
                "Upload exactly size_bytes to upload_url to start playback."
            ),
            structured_output=True,
        )
        async def play_file(
            target_id: str,
            filename: str,
            content_type: str,
            size_bytes: int,
            start_position_seconds: int = 0,
        ) -> dict[str, Any]:
            try:
                result = self.app.media_store.create_upload(
                    target_id,
                    filename,
                    content_type,
                    size_bytes,
                    start_position_seconds=start_position_seconds,
                )
            except (FilePlaybackError, PlaybackServiceError) as exc:
                raise self._tool_error(exc) from exc
            result["upload_url"] = self._public_origin() + result["upload_path"]
            return result

        @server.tool(
            description=(
                "Open a real-time PCM input for target_id. The only accepted "
                "format is s16le, 48000 Hz, stereo."
            ),
            structured_output=True,
        )
        async def open_pcm_stream(
            target_id: str,
            sample_format: str = "s16le",
            sample_rate: int = 48000,
            channels: int = 2,
        ) -> dict[str, Any]:
            try:
                result = await self.app.pcm_streams.create(
                    target_id,
                    sample_format=sample_format,
                    sample_rate=sample_rate,
                    channels=channels,
                )
            except (PcmStreamError, PlaybackServiceError) as exc:
                raise self._tool_error(exc) from exc
            origin = self._public_origin()
            result["stream_url"] = "ws" + origin[4:] + result["stream_path"]
            return result

        @server.tool(
            description="Get playback state and volume for target_id.",
            structured_output=True,
        )
        async def get_playback_status(target_id: str) -> dict[str, Any]:
            try:
                return await self.app.playback_service.get_status(target_id)
            except PlaybackServiceError as exc:
                raise self._tool_error(exc) from exc

        @server.tool(description="Pause playback on target_id.", structured_output=True)
        async def pause(target_id: str) -> dict[str, Any]:
            try:
                return await self.app.playback_service.pause(target_id)
            except PlaybackServiceError as exc:
                raise self._tool_error(exc) from exc

        @server.tool(
            description=(
                "Seek the current playback on target_id to an absolute number "
                "of seconds from the beginning. Pass if_session_id when known "
                "to avoid controlling a newer session."
            ),
            structured_output=True,
        )
        async def seek_playback(
            target_id: str,
            position_seconds: int,
            if_session_id: str | None = None,
        ) -> dict[str, Any]:
            try:
                return await self.app.playback_service.seek(
                    target_id,
                    position_seconds,
                    if_session_id=if_session_id,
                )
            except PlaybackServiceError as exc:
                raise self._tool_error(exc) from exc

        @server.tool(
            description="Stop playback and active Agent media on target_id.",
            structured_output=True,
        )
        async def stop(target_id: str) -> dict[str, Any]:
            try:
                return await self.app.stop_agent_playback(target_id)
            except PlaybackServiceError as exc:
                raise self._tool_error(exc) from exc

        @server.tool(
            description="Set target_id volume from 0 through 100.",
            structured_output=True,
        )
        async def set_volume(target_id: str, volume: int) -> dict[str, Any]:
            if isinstance(volume, bool) or volume < 0 or volume > 100:
                raise ToolError("INVALID_VOLUME")
            try:
                return await self.app.playback_service.set_volume(target_id, volume)
            except PlaybackServiceError as exc:
                raise self._tool_error(exc) from exc

    async def lifecycle(self, _web_app):
        async with self.server.session_manager.run():
            yield

    @staticmethod
    def _origin_allowed(request: web.Request) -> bool:
        origin = request.headers.get("Origin")
        if not origin:
            return True
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == request.host

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if not self._origin_allowed(request):
            return web.Response(status=403, text="Invalid Origin")
        if request.method != "POST":
            return web.Response(status=405, headers={"Allow": "POST"})
        body = await request.read()
        started: dict = {}
        response_body = bytearray()
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                started.update(message)
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
                if message.get("more_body"):
                    raise RuntimeError("streaming MCP responses are disabled")

        host, _, port_text = request.host.partition(":")
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": f"{request.version.major}.{request.version.minor}",
            "method": request.method,
            "scheme": request.scheme,
            "path": "/",
            "raw_path": b"/",
            "root_path": "/mcp",
            "query_string": request.query_string.encode("ascii", "ignore"),
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in request.headers.items()
            ],
            "server": (host, int(port_text) if port_text.isdigit() else None),
            "client": request.transport.get_extra_info("peername") if request.transport else None,
        }
        token = self._request_origin.set(request_public_origin(request))
        try:
            await self.asgi_app(scope, receive, send)
        finally:
            self._request_origin.reset(token)
        headers = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in started.get("headers", [])
        }
        return web.Response(
            status=started.get("status", 500),
            headers=headers,
            body=bytes(response_body),
        )
