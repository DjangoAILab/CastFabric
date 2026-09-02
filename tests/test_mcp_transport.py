from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from miair.app import CastFabric
from miair.config import Config
from miair.targets import OutputTargetConfig
from miair.web.api import create_web_app


def _build_app(tmp_path):
    target = OutputTargetConfig(
        id="uuid:living",
        name="Living",
        location="http://192.168.133.21/device.xml",
        virtual_udn="living-virtual",
    )
    config = Config(
        hostname="127.0.0.1",
        web_port=9988,
        conf_path=str(tmp_path),
        targets={target.id: target},
        default_target_id=target.id,
    )
    app = CastFabric(config)
    controller = SimpleNamespace(
        play_url=AsyncMock(return_value=True),
        seek=AsyncMock(return_value=True),
        pause=AsyncMock(return_value=True),
        stop=AsyncMock(return_value=True),
        set_volume=AsyncMock(return_value=True),
        get_status=AsyncMock(return_value={"status": 0, "volume": 20}),
    )
    app.suite_registry.register(target, "controller", controller)
    return config, app


@pytest.mark.asyncio
async def test_official_streamable_http_client_lists_and_calls_tools(tmp_path):
    config, app = _build_app(tmp_path)
    server = TestServer(create_web_app(config, app))
    await server.start_server()
    public_origin = str(server.make_url("/")).rstrip("/")
    try:
        async with streamable_http_client(str(server.make_url("/mcp"))) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                listed = await session.list_tools()
                result = await session.call_tool("list_outputs", {})
                play_result = await session.call_tool(
                    "play_url",
                    {
                        "target_id": "uuid:living",
                        "url": "https://media.example.test/notice.mp3",
                        "start_position_seconds": 30,
                    },
                )
                seek_result = await session.call_tool(
                    "seek_playback",
                    {
                        "target_id": "uuid:living",
                        "position_seconds": 45,
                    },
                )
                file_result = await session.call_tool(
                    "play_file",
                    {
                        "target_id": "uuid:living",
                        "filename": "notice.mp3",
                        "content_type": "audio/mpeg",
                        "size_bytes": 12,
                    },
                )
    finally:
        await server.close()
        await app.media_store.close()

    assert {tool.name for tool in listed.tools} == {
        "get_system_status",
        "list_outputs",
        "scan_outputs",
        "update_output",
        "play_url",
        "play_file",
        "seek_playback",
        "open_pcm_stream",
        "get_playback_status",
        "pause",
        "stop",
        "set_volume",
    }
    assert result.is_error is False
    assert result.structured_content["items"][0]["id"] == "uuid:living"
    assert play_result.structured_content["position_seconds"] == 30
    assert seek_result.structured_content["position_seconds"] == 45
    assert file_result.is_error is False
    assert file_result.structured_content["upload_url"].startswith(
        public_origin + "/api/v1/playback/files/"
    )
    schemas = {tool.name: tool.input_schema for tool in listed.tools}
    for name in {
        "update_output",
        "play_url",
        "play_file",
        "seek_playback",
        "open_pcm_stream",
        "get_playback_status",
        "pause",
        "stop",
        "set_volume",
    }:
        assert "target_id" in schemas[name]["required"]


@pytest.mark.asyncio
async def test_mcp_reuses_web_listener_and_rejects_cross_origin_requests(tmp_path):
    config, app = _build_app(tmp_path)
    client = TestClient(TestServer(create_web_app(config, app)))
    await client.start_server()
    try:
        rejected = await client.post(
            "/mcp",
            headers={"Origin": "https://attacker.invalid"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        no_sse = await client.get("/mcp")
    finally:
        await client.close()
        await app.media_store.close()

    assert rejected.status == 403
    assert no_sse.status == 405


@pytest.mark.asyncio
async def test_mcp_uses_forwarded_https_origin_for_agent_data_channels(tmp_path):
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
    client = TestClient(TestServer(create_web_app(config, app)))
    await client.start_server()
    try:
        http_client = create_mcp_http_client(
            headers={
                "Host": "mi-air.internal.wj2015.com",
                "X-Forwarded-Proto": "https",
            }
        )
        async with http_client, streamable_http_client(
            str(client.make_url("/mcp")), http_client=http_client
        ) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                file_result = await session.call_tool(
                    "play_file",
                    {
                        "target_id": "uuid:living",
                        "filename": "notice.wav",
                        "content_type": "audio/wav",
                        "size_bytes": 12,
                    },
                )
                pcm_result = await session.call_tool(
                    "open_pcm_stream",
                    {"target_id": "uuid:living"},
                )
    finally:
        await client.close()
        await app.media_store.close()

    assert file_result.structured_content["upload_url"].startswith(
        "https://mi-air.internal.wj2015.com/api/v1/playback/files/"
    )
    assert pcm_result.structured_content["stream_url"].startswith(
        "wss://mi-air.internal.wj2015.com/api/v1/playback/streams/"
    )
