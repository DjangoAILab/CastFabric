---
name: castfabric
description: Discover and manage CastFabric output speakers, play HTTP URLs or Agent-local audio files from an optional start time, seek current playback, stream real-time PCM, control playback, and run client-side playlists. Use for audio actions on a user's self-hosted CastFabric instance; do not use for generic media editing.
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
7. Keep playlists in the helper process. Read [references/playlist-schema.md](references/playlist-schema.md) only for playlist work.

## Helper commands

```text
node scripts/castfabric.mjs play-url  --target <id> <url>  [--start-seconds <seconds>]
node scripts/castfabric.mjs play-file --target <id> <path> [--start-seconds <seconds>]
node scripts/castfabric.mjs seek      --target <id> <absolute-seconds> [--if-session <session-id>]
```

Positions are non-negative whole seconds. Convert natural expressions such as `2:05` or “两分五秒” to `125` before calling the tool.

## Safety and lifecycle

- Require an exact target selection before any operation that plays sound.
- Listing, scanning, and status checks are silent; use them for connection verification.
- Do not add TTS, a media library, or a server-side queue.
- Do not treat `session_id`, `upload_id`, or an internal media URL as a reusable asset identifier.
- On interruption, close the local stream/playlist runner before calling `stop` so it cannot restart playback.
- Report CastFabric tool error codes without printing media bytes, upload tokens, or credentials.

The helper accepts `--server <CastFabric origin or /mcp URL>` or `CASTFABRIC_URL`.
