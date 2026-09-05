import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { buildFfmpegArgs, importPlaylist, mcpEndpoint, playLocalFile, positionSeconds, seekPlayback, uploadPersistentFile } from "../scripts/castfabric.mjs";

test("normalizes the MCP endpoint", () => {
  assert.equal(mcpEndpoint("http://castfabric:9988"), "http://castfabric:9988/mcp");
  assert.equal(mcpEndpoint("http://castfabric:9988/mcp"), "http://castfabric:9988/mcp");
});

test("builds fixed real-time PCM FFmpeg arguments", () => {
  const file = buildFfmpegArgs("song.mp3", false);
  assert.deepEqual(file.slice(0, 7), ["-hide_banner", "-loglevel", "error", "-re", "-i", "song.mp3", "-f"]);
  assert.deepEqual(file.slice(-8), ["s16le", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2", "pipe:1"]);
  assert.equal(buildFfmpegArgs(null, true).includes("-re"), false);
});

test("accepts only non-negative whole-second positions", () => {
  assert.equal(positionSeconds("125"), 125);
  assert.equal(positionSeconds(0), 0);
  assert.throws(() => positionSeconds("1.5"), /INVALID_POSITION/);
  assert.throws(() => positionSeconds(-1), /INVALID_POSITION/);
});

test("creates an MCP file transaction and uploads exact local bytes", async () => {
  const directory = await mkdtemp(join(tmpdir(), "castfabric-skill-"));
  const path = join(directory, "notice.mp3");
  await writeFile(path, Buffer.from("abcdef"));
  let uploaded = null;
  const toolCalls = [];
  const server = createServer(async (request, response) => {
    if (request.url === "/upload" && request.method === "PUT") {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      uploaded = Buffer.concat(chunks);
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ ok: true, state: "playing" }));
      return;
    }
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const message = JSON.parse(Buffer.concat(chunks).toString() || "{}");
    if (!message.id) {
      response.writeHead(202);
      response.end();
      return;
    }
    const result = message.method === "initialize"
      ? { protocolVersion: "2025-11-25", capabilities: {}, serverInfo: { name: "fake", version: "1" } }
      : (() => {
          toolCalls.push({ name: message.params.name, arguments: message.params.arguments });
          return { content: [], structuredContent: { upload_url: `http://127.0.0.1:${server.address().port}/upload` }, isError: false };
        })();
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ jsonrpc: "2.0", id: message.id, result }));
  });
  await new Promise((accept) => server.listen(0, "127.0.0.1", accept));
  try {
    const result = await playLocalFile(`http://127.0.0.1:${server.address().port}`, "uuid:living", path, 75);
    assert.equal(result.state, "playing");
    assert.deepEqual(uploaded, await readFile(path));
    assert.equal(toolCalls[0].name, "play_file");
    assert.equal(toolCalls[0].arguments.start_position_seconds, 75);

    await seekPlayback(
      `http://127.0.0.1:${server.address().port}`,
      "uuid:living",
      125,
      "session-current",
    );
    assert.deepEqual(toolCalls[1], {
      name: "seek_playback",
      arguments: {
        target_id: "uuid:living",
        position_seconds: 125,
        if_session_id: "session-current",
      },
    });
    const persistent = await uploadPersistentFile(
      `http://127.0.0.1:${server.address().port}`, path, "Notice",
    );
    assert.equal(persistent.ok, true);
    assert.equal(toolCalls[2].name, "begin_media_upload");
    assert.equal(toolCalls[2].arguments.display_name, "Notice");
  } finally {
    await new Promise((accept) => server.close(accept));
    await rm(directory, { recursive: true });
  }
});

test("imports a manifest once without running or polling the playlist", async () => {
  const directory = await mkdtemp(join(tmpdir(), "castfabric-import-"));
  const path = join(directory, "playlist.json");
  await writeFile(path, JSON.stringify({
    version: 1,
    name: "Morning",
    items: [{type: "url", url: "https://example.test/song.mp3", title: "Song"}],
  }));
  const toolCalls = [];
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const message = JSON.parse(Buffer.concat(chunks).toString() || "{}");
    if (!message.id) { response.writeHead(202); response.end(); return; }
    let result;
    if (message.method === "initialize") {
      result = {protocolVersion: "2025-11-25", capabilities: {}, serverInfo: {name: "fake", version: "1"}};
    } else {
      const name = message.params.name;
      toolCalls.push(name);
      const structuredContent = name === "create_playlist"
        ? {item: {id: "playlist-one", revision: 1}}
        : name === "create_url_media_asset"
          ? {item: {id: "asset-one"}}
          : name === "get_playlist"
            ? {item: {id: "playlist-one", revision: 2}}
            : {ok: true};
      result = {content: [], structuredContent, isError: false};
    }
    response.writeHead(200, {"content-type": "application/json"});
    response.end(JSON.stringify({jsonrpc: "2.0", id: message.id, result}));
  });
  await new Promise((accept) => server.listen(0, "127.0.0.1", accept));
  try {
    const result = await importPlaylist(`http://127.0.0.1:${server.address().port}`, path);
    assert.equal(result.item.id, "playlist-one");
    assert.deepEqual(toolCalls, [
      "create_playlist", "create_url_media_asset", "mutate_playlist_items",
      "get_playlist", "get_playlist",
    ]);
    assert.equal(toolCalls.includes("get_playback_status"), false);
    assert.equal(toolCalls.includes("start_playlist"), false);
  } finally {
    await new Promise((accept) => server.close(accept));
    await rm(directory, {recursive: true});
  }
});
