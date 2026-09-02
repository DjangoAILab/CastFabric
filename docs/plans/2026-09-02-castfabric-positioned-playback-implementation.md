# CastFabric Positioned Playback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add atomic play-at and current-session seek across CastFabric's application service, HTTP, MCP, and packaged Skill without adding media IDs or persistent file management.

**Architecture:** Extend the protocol-neutral output port with integer-second seek and keep all orchestration in `PlaybackService`. Store the optional initial position only in the existing one-time upload transaction; expose the same semantics through HTTP and MCP while the Skill remains a local-byte helper.

**Tech Stack:** Python 3.10+, aiohttp, official MCP Python SDK, UPnP AVTransport, Node.js 22 built-ins, pytest, Node test runner.

---

## Hard verification boundary

Never call play, seek, pause, stop, or volume against the Home Server's physical renderer during this plan. Use only unit fakes, the in-process Fake DMR integration test, static MCP discovery, and read-only status/capability checks.

### Task 1: Protocol-neutral seek port

**Files:** `miair/outputs/base.py`, `miair/outputs/dlna.py`, `miair/outputs/xiaomi.py`, `miair/dlna/client.py`, `miair/speaker.py`, `tests/test_output_targets.py`, `tests/test_local_dlna_client.py`

1. Add failing tests for `REL_TIME` formatting, DLNA delegation, and fallback behavior.
2. Run the focused tests and confirm the missing methods fail.
3. Add `seek(position_seconds: int)` to the output protocol, adapters, facade, and local DLNA client. Xiaomi returns unsupported without a cloud-side emulation.
4. Run the focused tests and commit with the application batch.

### Task 2: Atomic application semantics

**Files:** `miair/playback/service.py`, `miair/playback/files.py`, `tests/test_playback_service.py`, `tests/test_playback_files.py`

1. Add failing tests for play-at ordering, zero-offset behavior, invalid positions, optional session precondition, upload transaction propagation, and seek failure cleanup.
2. Extend `PlaybackService.play_url()` and add `PlaybackService.seek()`.
3. Store the initial position only in `PendingUpload` and consume it when upload completes.
4. Verify no public or persistent media ID exists.

### Task 3: HTTP and MCP contracts

**Files:** `miair/web/api_v1.py`, `miair/mcp/server.py`, `tests/test_api_v1.py`, `tests/test_mcp_transport.py`

1. Add HTTP tests for optional start position on URL/file playback and `POST /api/v1/playback/{target_id}/seek`.
2. Add MCP schema/call tests for optional play-at fields and the new `seek_playback` tool.
3. Validate non-negative integer seconds and map service errors without leaking URLs or tokens.
4. Run focused HTTP/MCP tests.

### Task 4: Agent Skill helper

**Files:** `skills/castfabric/SKILL.md`, `skills/castfabric/scripts/castfabric.mjs`, `skills/castfabric/references/playlist-schema.md`, `skills/castfabric/tests/castfabric.test.mjs`

1. Add Node tests proving `--start-seconds` is sent in the initial play/file transaction and standalone `seek` maps to `seek_playback`.
2. Support optional `start_seconds` in playlist items.
3. Document natural-language minute/second conversion and keep playback orchestration server-side.
4. Run Node tests and the Skill validator.

### Task 5: Regression, release, and silent OpenClaw install

**Files:** `README.md`, `README.en.md`, `docs/project/CURRENT_STATE.md`, `docs/testing/castfabric-home-server-checklist.md`, `pyproject.toml`, `miair/const.py`

1. Update public capability counts, contracts, version, and the user-provided real-device incident record.
2. Run all Python tests, Agent Skill tests, offline MiPlay self-test, `git diff --check`, and version synchronization.
3. Commit and push `main`; tag the next prerelease only after CI passes, then verify the tag release workflow.
4. Install the released repository Skill into `vm-jeffrey` OpenClaw.
5. Verify only `openclaw skills info/list/check` and MCP tool discovery. Do not invoke any sound-producing tool.
