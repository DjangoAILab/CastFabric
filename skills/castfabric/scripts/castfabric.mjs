#!/usr/bin/env node

import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";
import { spawn } from "node:child_process";

export function mcpEndpoint(value) {
  const raw = String(value || "").replace(/\/$/, "");
  if (!/^https?:\/\//.test(raw)) throw new Error("CastFabric server must be HTTP(S)");
  return raw.endsWith("/mcp") ? raw : `${raw}/mcp`;
}

async function postMcp(endpoint, message, fetchImpl = fetch) {
  const response = await fetchImpl(endpoint, {
    method: "POST",
    headers: {
      accept: "application/json, text/event-stream",
      "content-type": "application/json",
      "mcp-protocol-version": "2025-11-25",
    },
    body: JSON.stringify(message),
  });
  if (response.status === 202) return null;
  if (!response.ok) throw new Error(`MCP_HTTP_${response.status}`);
  return response.json();
}

export async function mcpCall(server, name, args = {}, fetchImpl = fetch) {
  const endpoint = mcpEndpoint(server);
  await postMcp(endpoint, {
    jsonrpc: "2.0", id: 1, method: "initialize",
    params: {
      protocolVersion: "2025-11-25",
      capabilities: {},
      clientInfo: { name: "castfabric-skill", version: "1" },
    },
  }, fetchImpl);
  await postMcp(endpoint, {
    jsonrpc: "2.0", method: "notifications/initialized",
  }, fetchImpl);
  const payload = await postMcp(endpoint, {
    jsonrpc: "2.0", id: 2, method: "tools/call",
    params: { name, arguments: args },
  }, fetchImpl);
  if (payload?.error) throw new Error(payload.error.message || "MCP_ERROR");
  const result = payload?.result;
  if (result?.isError) throw new Error(result.content?.[0]?.text || "CASTFABRIC_TOOL_ERROR");
  return result?.structuredContent ?? JSON.parse(result?.content?.[0]?.text || "null");
}

export function positionSeconds(value) {
  const number = Number(value ?? 0);
  if (!Number.isSafeInteger(number) || number < 0) throw new Error("INVALID_POSITION");
  return number;
}

function withStartPosition(args, value) {
  const position = positionSeconds(value);
  return position > 0 ? { ...args, start_position_seconds: position } : args;
}

export async function playUrl(server, targetId, url, startPositionSeconds = 0, fetchImpl = fetch) {
  return mcpCall(server, "play_url", withStartPosition({
    target_id: targetId,
    url,
  }, startPositionSeconds), fetchImpl);
}

export async function seekPlayback(server, targetId, position, ifSessionId = null, fetchImpl = fetch) {
  const args = {
    target_id: targetId,
    position_seconds: positionSeconds(position),
  };
  if (ifSessionId) args.if_session_id = ifSessionId;
  return mcpCall(server, "seek_playback", args, fetchImpl);
}

export async function playLocalFile(server, targetId, path, startPositionSeconds = 0, fetchImpl = fetch) {
  // Keep the original four-argument helper compatible for existing callers.
  if (typeof startPositionSeconds === "function") {
    fetchImpl = startPositionSeconds;
    startPositionSeconds = 0;
  }
  const absolute = resolve(path);
  const details = await stat(absolute);
  if (!details.isFile()) throw new Error("LOCAL_FILE_NOT_FOUND");
  const transaction = await mcpCall(server, "play_file", withStartPosition({
    target_id: targetId,
    filename: basename(absolute),
    content_type: contentType(absolute),
    size_bytes: details.size,
  }, startPositionSeconds), fetchImpl);
  const response = await fetchImpl(transaction.upload_url, {
    method: "PUT",
    headers: { "content-type": "application/octet-stream" },
    body: createReadStream(absolute),
    duplex: "half",
  });
  if (!response.ok) throw new Error(`UPLOAD_HTTP_${response.status}`);
  return response.json();
}

export async function uploadPersistentFile(server, path, displayName = null, fetchImpl = fetch) {
  const absolute = resolve(path);
  const details = await stat(absolute);
  if (!details.isFile()) throw new Error("LOCAL_FILE_NOT_FOUND");
  const args = {
    filename: basename(absolute),
    content_type: contentType(absolute),
    size_bytes: details.size,
  };
  if (displayName) args.display_name = displayName;
  const transaction = await mcpCall(server, "begin_media_upload", args, fetchImpl);
  const response = await fetchImpl(transaction.upload_url, {
    method: "PUT",
    headers: { "content-type": "application/octet-stream" },
    body: createReadStream(absolute),
    duplex: "half",
  });
  if (!response.ok) throw new Error(`UPLOAD_HTTP_${response.status}`);
  return response.json();
}

export async function importPlaylist(server, manifestPath, fetchImpl = fetch) {
  const absolute = resolve(manifestPath);
  const manifest = JSON.parse(await readFile(absolute, "utf8"));
  if (manifest.version !== 1 || !manifest.name || !Array.isArray(manifest.items) || !manifest.items.length) {
    throw new Error("INVALID_PLAYLIST");
  }
  const created = await mcpCall(server, "create_playlist", {
    name: manifest.name,
    ...(manifest.description ? { description: manifest.description } : {}),
    ...(manifest.default_order ? { default_order: manifest.default_order } : {}),
    ...(manifest.default_repeat ? { default_repeat: manifest.default_repeat } : {}),
  }, fetchImpl);
  const playlistId = created.item.id;
  let revision = created.item.revision;
  for (const item of manifest.items) {
    let assetId;
    if (item.type === "file") {
      const uploaded = await uploadPersistentFile(
        server, resolve(dirname(absolute), item.path), item.title || null, fetchImpl,
      );
      assetId = uploaded.asset.id;
    } else if (item.type === "url") {
      const asset = await mcpCall(server, "create_url_media_asset", {
        url: item.url, display_name: item.title || item.url,
      }, fetchImpl);
      assetId = asset.item.id;
    } else {
      throw new Error("INVALID_PLAYLIST_ITEM");
    }
    await mcpCall(server, "mutate_playlist_items", {
      playlist_id: playlistId, operation: "add", expected_revision: revision,
      asset_id: assetId, ...(item.title ? { title: item.title } : {}),
    }, fetchImpl);
    const refreshed = await mcpCall(server, "get_playlist", { playlist_id: playlistId }, fetchImpl);
    revision = refreshed.item.revision;
  }
  return mcpCall(server, "get_playlist", { playlist_id: playlistId }, fetchImpl);
}

function contentType(path) {
  const extension = path.toLowerCase().split(".").pop();
  return ({ mp3: "audio/mpeg", wav: "audio/wav", flac: "audio/flac", m4a: "audio/mp4", aac: "audio/aac", ogg: "audio/ogg" })[extension] || "application/octet-stream";
}

export function buildFfmpegArgs(input, stdin = false) {
  const source = stdin ? ["-i", "pipe:0"] : ["-re", "-i", input];
  return ["-hide_banner", "-loglevel", "error", ...source,
    "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2", "pipe:1"];
}

async function openWebSocket(url) {
  const socket = new WebSocket(url);
  await new Promise((accept, reject) => {
    socket.addEventListener("open", accept, { once: true });
    socket.addEventListener("error", () => reject(new Error("PCM_WEBSOCKET_FAILED")), { once: true });
  });
  return socket;
}

export async function streamInput(server, targetId, input, stdin = false) {
  const session = await mcpCall(server, "open_pcm_stream", {
    target_id: targetId, sample_format: "s16le", sample_rate: 48000, channels: 2,
  });
  const socket = await openWebSocket(session.stream_url);
  const ffmpeg = spawn("ffmpeg", buildFfmpegArgs(input, stdin), {
    stdio: [stdin ? "inherit" : "ignore", "pipe", "inherit"],
  });
  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    ffmpeg.kill("SIGTERM");
    socket.close();
    await mcpCall(server, "stop", { target_id: targetId }).catch(() => {});
  };
  process.once("SIGINT", stop);
  process.once("SIGTERM", stop);
  try {
    for await (const chunk of ffmpeg.stdout) {
      while (socket.bufferedAmount > 512 * 1024) {
        await new Promise((accept) => setTimeout(accept, 10));
      }
      socket.send(chunk);
    }
    const code = await new Promise((accept) => ffmpeg.once("close", accept));
    if (!stopping && code !== 0) throw new Error(`FFMPEG_EXIT_${code}`);
  } catch (error) {
    await stop();
    throw error;
  } finally {
    process.off("SIGINT", stop);
    process.off("SIGTERM", stop);
    socket.close();
  }
}

function parse(argv) {
  const args = [...argv];
  let server = process.env.CASTFABRIC_URL;
  const index = args.indexOf("--server");
  if (index >= 0) server = args.splice(index, 2)[1];
  if (!server) throw new Error("Set CASTFABRIC_URL or pass --server");
  return { server, args };
}

function option(args, name) {
  const index = args.indexOf(name);
  if (index < 0 || !args[index + 1]) throw new Error(`Missing ${name}`);
  return args[index + 1];
}

async function runCli(argv) {
  const { server, args } = parse(argv);
  const command = args[0];
  const target = args.includes("--target") ? option(args, "--target") : null;
  const targetValue = target ? args[args.indexOf("--target") + 2] : null;
  const startPosition = args.includes("--start-seconds")
    ? positionSeconds(option(args, "--start-seconds"))
    : 0;
  let result;
  if (command === "outputs") {
    result = await mcpCall(server, args[1] === "scan" ? "scan_outputs" : "list_outputs");
  } else if (command === "play-url") {
    result = await playUrl(server, target, targetValue, startPosition);
  } else if (command === "play-file") {
    result = await playLocalFile(server, target, targetValue, startPosition);
  } else if (command === "upload-file") {
    result = await uploadPersistentFile(
      server, args[1], args.includes("--name") ? option(args, "--name") : null,
    );
  } else if (command === "import-playlist") {
    result = await importPlaylist(server, args[1]);
  } else if (command === "seek") {
    result = await seekPlayback(
      server,
      target,
      targetValue,
      args.includes("--if-session") ? option(args, "--if-session") : null,
    );
  } else if (command === "stream") {
    await streamInput(server, target, args.includes("--stdin") ? null : option(args, "--input"), args.includes("--stdin"));
    return;
  } else if (["status", "pause", "resume", "stop"].includes(command)) {
    result = await mcpCall(server, command === "status" ? "get_playback_status" : command, { target_id: target });
  } else if (command === "volume") {
    result = await mcpCall(server, "set_volume", { target_id: target, volume: Number(args.at(-1)) });
  } else {
    throw new Error("Unknown command");
  }
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runCli(process.argv.slice(2)).catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
