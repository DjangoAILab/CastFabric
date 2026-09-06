# CastFabric Server Playlists Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add persistent audio resources, server-run playlists, playback history, and explicit resume across Core, SQLite, HTTP, MCP, Agent Skill/helper, and the production console without expanding beyond the approved six-table model.

**Architecture:** A single `ContentRepository` owns schema migration and short SQLite transactions. `MediaAssetService` owns managed blobs, external URLs, and in-memory upload tickets; `PlaylistService` owns definitions and a per-target asyncio runner over the existing `PlaybackService`. HTTP and MCP remain thin adapters over those application services, while existing ingress sessions are persisted through the same repository.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, `asyncio`, aiohttp, official MCP SDK, vanilla HTML/CSS/JavaScript, Node.js helper/tests, Docker.

---

### Task 1: Lock the approved contract and replacement ADR

**Files:**
- Modify: `docs/plans/2026-09-04-castfabric-media-playlists-design.md`
- Modify: `docs/plans/2026-09-04-castfabric-media-playlists-product-audit.md`
- Create: `docs/adr/0011-persist-media-assets-and-run-server-playlists.md`
- Include: `docs/design/research/2026-09-04-castfabric-media-playlist-study.md`
- Include: `docs/design/contracts/castfabric-playlists-fields.json`
- Include: `docs/prototypes/castfabric-server-playlists-product-flow-v3.html`

**Steps:**
1. Mark the functional prototype accepted on 2026-09-05 and make v3 the production behavior reference.
2. Record that ADR-0011 replaces ADR-0009/0010 only for persistent assets and server playlists, preserving thin MCP and positioned playback primitives.
3. State the six-table ceiling, failure-stops rule, no-WAL/no-worker boundary, and user-facing object model.
4. Run `python3 docs/prototypes/validate_console_prototype.py docs/prototypes/castfabric-server-playlists-product-flow-v3.html docs/design/contracts/castfabric-playlists-fields.json` and `git diff --check`.
5. Commit only task design/prototype files; exclude `docs/research/2026-09-03-nfc-touch-integration-research.md` and the session prompt.

### Task 2: Build and migrate the six-table SQLite repository

**Files:**
- Create: `miair/content/__init__.py`
- Create: `miair/content/repository.py`
- Create: `tests/test_content_repository.py`
- Modify: `miair/runtime/events.py`
- Modify: `miair/runtime/sessions.py`
- Modify: `tests/test_activity_events.py`
- Modify: `tests/test_media_sessions.py`

**Steps:**
1. Write failing tests for cold creation, explicit `PRAGMA user_version`, foreign keys, ordered migration, and exactly the six approved business tables.
2. Add tests proving one active session and one active run per target, independent targets, restart-to-interrupted, and stale session/run fencing.
3. Implement `ContentRepository` with one connection, `check_same_thread=False`, a process-local lock, foreign keys, default journal mode, explicit transactions, and repository-owned serialization/redaction.
4. Route new activity writes and all new/ordinary media-session lifecycle writes to SQLite; do not import, delete, or append to legacy `activity.jsonl`.
5. Run `python -m pytest -q tests/test_content_repository.py tests/test_activity_events.py tests/test_media_sessions.py` and commit.

### Task 3: Add persistent media assets and upload tickets

**Files:**
- Create: `miair/content/media.py`
- Create: `tests/test_media_assets.py`
- Modify: `miair/web/api_v1.py`
- Modify: `tests/test_api_v1.py`

**Steps:**
1. Write failing tests for external URL create/update/redaction, metadata editing, search/filter/sort/pagination, and conservative delete.
2. Write failing tests for raw PUT upload size/expiry/one-use validation, audio probing, safe original filenames, SHA-256 blob deduplication, and `.part` cleanup.
3. Implement managed directories at `<conf>/media/blobs` and `<conf>/media/uploads`, keeping upload tickets only in memory.
4. Add persistent-media HTTP create/list/get/update/delete/play and upload routes, all returning stable top-level error categories plus `reason/details`.
5. Run `python -m pytest -q tests/test_media_assets.py tests/test_api_v1.py tests/test_playback_files.py` and commit.

### Task 4: Implement playlist definitions, revision checks, and active-item conflicts

**Files:**
- Create: `miair/content/playlists.py`
- Create: `tests/test_playlist_service.py`

**Steps:**
1. Write failing CRUD tests for playlist name/description/defaults and item add/update/remove/reorder with contiguous positions.
2. Add tests for revision mismatch, archived/empty playlist rules, title fallback, live-definition next selection, history-based previous selection, and only-current-item conflict detection.
3. Implement the minimal service API and structured `keep/reload/stop` resolution without revision snapshots or queue tables.
4. Run `python -m pytest -q tests/test_playlist_service.py tests/test_content_repository.py` and commit.

### Task 5: Run playlists on the server and persist progress

**Files:**
- Modify: `miair/content/playlists.py`
- Modify: `miair/playback/service.py`
- Modify: `miair/app.py`
- Create: `tests/test_playlist_runner.py`
- Modify: `tests/test_playback_service.py`

**Steps:**
1. Write failing fake-controller tests for sequential/random, repeat none/all, previous/next/select, explicit resume, and two targets running the same playlist independently.
2. Add fencing and preemption tests proving delayed commands cannot mutate a replacement run/session and ordinary playback ends a prior playlist run.
3. Implement one asyncio runner task per active target, fixed-interval status observation, explicit progress persistence, and start/pause/resume/stop/navigation controls.
4. Treat an unambiguous stopped-after-playing state as item completion; treat ambiguous disappearance/restart as interrupted; on every item/output error record reason and stop without retry, skip, or fallback.
5. Wire startup interruption and shutdown cancellation without automatic sound.
6. Run `python -m pytest -q tests/test_playlist_runner.py tests/test_playlist_service.py tests/test_playback_service.py tests/test_media_sessions.py` and commit.

### Task 6: Expose one HTTP application contract

**Files:**
- Modify: `miair/web/api_v1.py`
- Modify: `tests/test_api_v1.py`
- Create: `tests/test_playlist_api.py`

**Steps:**
1. Write failing integration tests for resource and playlist CRUD, item mutations, start/resume/control, progress candidates, and read-only playback history.
2. Add parity tests for revision conflict, active-item conflict, session/run fences, redacted URLs, and the five top-level error categories.
3. Register thin aiohttp routes that call `MediaAssetService` and `PlaylistService`; keep existing URL/file/PCM routes compatible.
4. Run `python -m pytest -q tests/test_playlist_api.py tests/test_api_v1.py` and commit.

### Task 7: Add short-call MCP tools with HTTP parity

**Files:**
- Modify: `miair/mcp/server.py`
- Modify: `tests/test_mcp_transport.py`
- Create: `tests/test_playlist_mcp.py`

**Steps:**
1. Write failing discovery and call tests for consolidated media, playlist, run-control, progress, history, and persistent-upload tools.
2. Verify start returns immediately with `run_id/session_id`, tools never poll, and errors match HTTP category/reason/details without URL secrets or upload tokens.
3. Implement MCP tools as thin calls to the same application services.
4. Run `python -m pytest -q tests/test_playlist_mcp.py tests/test_mcp_transport.py tests/test_playlist_api.py` and commit.

### Task 8: Thin the Agent Skill and helper

**Files:**
- Modify: `skills/castfabric/SKILL.md`
- Modify: `skills/castfabric/scripts/castfabric.mjs`
- Modify: `skills/castfabric/references/playlist-schema.md`
- Modify: `skills/castfabric/tests/castfabric.test.mjs`

**Steps:**
1. Write failing Node tests for `upload-file` and one-shot `import-playlist`, including mixed file/URL manifests and cleanup on SIGINT for PCM only.
2. Delete the client-side playlist loop and `waitUntilStopped`; make import create persistent assets/items and one server playlist, then exit.
3. Update the Skill so the server is the only playlist/progress fact source and conflict/resume choices remain explicit.
4. Run `node --test skills/castfabric/tests/*.test.mjs` and commit.

### Task 9: Implement the accepted production content workspace

**Files:**
- Modify: `miair/web/static/index.html`
- Modify: `miair/web/static/console.js`
- Modify: `miair/web/static/console.css`
- Modify: `tests/fixtures/console_contract.json`
- Modify: `tests/test_console_contract.py`

**Steps:**
1. Write failing contract tests for the Playlists main nav and Playlist/Audio Resources/Playback Record subviews, with no playback action in history.
2. Implement API-backed list/detail, explicit edit mode, shared searchable asset picker, metadata editor, single-output picker, active-run controls, and capability-aware progress.
3. Preserve Overview/Speakers/Activity/AI responsibilities; add only contextual playlist controls and update AI copy to server-run playlists.
4. Cover Chinese/English and desktop/mobile plus empty/loading/unavailable/offline/conflict/storage-error states using semantic buttons and inline SVG icons.
5. Run console contract tests, serve locally, and inspect desktop/mobile interactions in the browser before committing.

### Task 10: Full regression, container, documentation, and candidate publication

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/project/CURRENT_STATE.md`
- Modify: `docs/testing/castfabric-home-server-checklist.md`
- Add/modify focused integration tests under `tests/`

**Steps:**
1. Run `python -m pytest -q`, `node --test skills/castfabric/tests/*.test.mjs`, `python -m miair.miplay.probe self-test --duration 0.35`, and `git diff --check` with workspace Python 3.12+.
2. Verify fake DMR pull and automatic item transition, legacy config upgrade, database/media persistence across restart, privacy, and no regressions in DLNA/AirPlay/MiPlay/URL/file/PCM/seek/volume.
3. Commit documentation, push `codex/server-playlists` to `origin`, wait for every feature-branch CI job, and repair failures rather than bypassing them.
4. Build or dispatch a commit-addressed `linux/amd64` candidate and record immutable tag/digest; do not merge main or create a release.

### Task 11: Home Server deployment and layered acceptance

**Files:**
- Modify: `docs/testing/castfabric-home-server-checklist.md`
- Modify: `docs/project/CURRENT_STATE.md`

**Steps:**
1. Read current deployment through existing secure configuration; record container/image/digest/start time, host-network/config mount, health/suites/active playback, current volume, and free disk without printing secrets or full network addresses.
2. Create a stopped, dated rollback identity from the currently running known-good service and verify its image/config/mount without running it beside production.
3. Run the candidate in an isolated temporary config and non-conflicting web port with all receiver protocols disabled; verify cold schema, CRUD/upload/MCP, restart persistence, and redaction.
4. Replace the sole production container with the same immutable candidate, then verify TLS/static assets, bilingual console, system health, target IDs/suite readiness, MCP discovery, content/history state, persistent SQLite/media, restart persistence, privacy, and zero unexpected active runs/sessions.
5. On any regression, immediately restore the new rollback container and verify health before analysis.
6. After silent acceptance passes, stop at the required real-speaker gate and request permission naming target(s), approximate duration, and restoration behavior.
7. With permission, verify audible two-item transition, transport/navigation/seek, server continuation after helper exit, independent two-speaker progress if authorized, progress/history, active-item conflict, and final stop/volume restoration/zero active state.
8. Record commit, CI run, image digest, deployment time, rollback identity, silent/device evidence, and unverified items; commit and push the final documentation update, confirm CI and deployed commit, then mark the Goal complete.
