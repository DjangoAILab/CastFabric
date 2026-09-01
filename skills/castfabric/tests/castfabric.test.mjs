import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { buildFfmpegArgs, mcpEndpoint, playLocalFile } from "../scripts/castfabric.mjs";

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

test("creates an MCP file transaction and uploads exact local bytes", async () => {
  const directory = await mkdtemp(join(tmpdir(), "castfabric-skill-"));
  const path = join(directory, "notice.mp3");
  await writeFile(path, Buffer.from("abcdef"));
  let uploaded = null;
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
      : { content: [], structuredContent: { upload_url: `http://127.0.0.1:${server.address().port}/upload` }, isError: false };
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ jsonrpc: "2.0", id: message.id, result }));
  });
  await new Promise((accept) => server.listen(0, "127.0.0.1", accept));
  try {
    const result = await playLocalFile(`http://127.0.0.1:${server.address().port}`, "uuid:living", path);
    assert.equal(result.state, "playing");
    assert.deepEqual(uploaded, await readFile(path));
  } finally {
    await new Promise((accept) => server.close(accept));
    await rm(directory, { recursive: true });
  }
});
