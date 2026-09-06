---
name: castfabric
description: Discover CastFabric speakers, manage reusable media and server-side playlists, control playback, upload Agent-local audio, and stream real-time PCM. Use for audio actions on a user's self-hosted CastFabric instance; do not use for generic media editing.
---

# CastFabric

Use the configured CastFabric Streamable HTTP MCP endpoint for speaker management and playback.

## Routing

1. Call `list_outputs` before choosing a speaker. Never invent `target_id`.
2. If the requested speaker is absent, call `scan_outputs`, then ask the user only when more than one plausible target remains.
3. Use MCP `play_url` for an accessible HTTP(S) audio URL. Set `start_position_seconds` when the user asks to begin new playback at a specific time; do not issue a second Agent-side seek.
4. For an Agent-local file, run `node scripts/castfabric.mjs play-file`; it creates the MCP upload transaction and sends raw bytes to the one-time URL. Pass `--start-seconds <integer>` for positioned playback. The upload ID is a one-time transfer handle, not a reusable media ID.
5. Use MCP `seek_playback` to move the current playback to an absolute `position_seconds`. Pass the known `session_id` as `if_session_id` when available so a delayed command cannot seek newer playback.
6. Use `stream` only for stdin, continuous sources, or explicitly requested real-time decoding. It requires FFmpeg and always sends `s16le / 48000 Hz / stereo` PCM. Positioned playback is not defined for a live PCM stream.
7. Use MCP Playlist tools for all playlist state and execution. `start_playlist` returns immediately; never poll to keep it running.
8. For “继续”, call `get_playlist_progress`, explain the matching candidates, then explicitly call `start_playlist` with the selected item, position, and prior session ID. Playback history alone never implies continuation.
9. Before changing or removing a currently playing item, explain affected runs and obtain one explicit `keep`, `reload`, or `stop` resolution.
10. Read [references/playlist-schema.md](references/playlist-schema.md) only for a one-time local manifest import.

## Helper commands

```text
node scripts/castfabric.mjs play-url  --target <id> <url>  [--start-seconds <seconds>]
node scripts/castfabric.mjs play-file --target <id> <path> [--start-seconds <seconds>]
node scripts/castfabric.mjs upload-file <path> [--name <display-name>]
node scripts/castfabric.mjs import-playlist <manifest.json>
node scripts/castfabric.mjs seek      --target <id> <absolute-seconds> [--if-session <session-id>]
```

Positions are non-negative whole seconds. Convert natural expressions such as `2:05` or “两分五秒” to `125` before calling the tool.

## Safety and lifecycle

- Require an exact target selection before any operation that plays sound.
- Listing, scanning, and status checks are silent; use them for connection verification.
- Do not add TTS, a general media library, or a queue.
- Do not treat `session_id`, `upload_id`, or an internal media URL as a reusable asset identifier.
- Only a live PCM helper owns a long-running local process. Server playlists continue after the helper exits.
- Report CastFabric tool error codes without printing media bytes, upload tokens, or credentials.

The helper accepts `--server <CastFabric origin or /mcp URL>` or `CASTFABRIC_URL`.
