# Header, dialog and media metadata Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the approved A-direction header/dialog, correct MP3 durations, preserve the two populated playlists, and merge, release and deploy the verified result.

**Architecture:** Reuse the existing vanilla console and canonical SVG. Probe only managed local audio with the already-installed PyAV dependency; backfill only missing durations, without new tables, APIs, workers or playback behavior. Keep the existing feature branch in this user-selected workspace and preserve unrelated untracked files.

**Tech Stack:** Python 3.12, aiohttp, SQLite, PyAV, vanilla HTML/CSS/JS, pytest, Node helper tests, Chrome, Docker/GHCR, GitHub Actions.

---

Approval: user accepted the A prototype on 2026-09-06 and authorized implementation; prior merge/push/release authorization remains in force. No new sound test is required or authorized here.

### 1. Regression tests, then metadata fix

Files: `tests/test_media_assets.py`, `tests/test_playlist_service.py`, `miair/content/media.py`, `miair/content/repository.py`, `miair/content/playlists.py`, `miair/app.py`.

1. Add real locally encoded MP3 upload test and missing-duration backfill/restart test; assert unknown totals are null, not zero, and existing metadata/IDs/revisions do not change.
2. Run `.venv/bin/python -m pytest tests/test_media_assets.py tests/test_playlist_service.py -q`; new cases must fail before implementation.
3. Retain WAV fast path; use `av.open(local_file, format=whitelisted_format)` and audio-stream duration or container duration. Accept only finite positive results; malformed/unknown input remains null. Do not fetch external URLs.
4. Add repository queries for available managed assets with missing duration and a conditional metadata-only update (`WHERE duration_seconds IS NULL`). Probe outside write transactions. Run the bounded local backfill after Web starts via `asyncio.to_thread`.
5. Return `None` for a nonempty playlist when any duration is unknown; an empty playlist totals zero. Run focused tests, then commit this tested change together with its approval/plan records.

### 2. Approved UI implementation

Files: `miair/web/static/index.html`, `console.css`, `console.js`, `castfabric-mark.svg`, `github-mark.svg`, `THIRD_PARTY_NOTICES.md`, `tests/test_console_contract.py`.

1. Add contracts for exact canonical logo bytes, repo URL, current-language label/popover, and scoped modal layout.
2. Reuse README SVG and licensed GitHub SVG; show Source code / current language / Connections as a secondary utility group. Keep real navigation and settings handlers.
3. Scope centering to `#contentModal.open` with `display:flex; align-items:center; justify-content:center`. Limit dialog to viewport minus safe margins; only body scrolls. Header/footer cannot shrink. Use SVG close, descriptive create action, native labels and inline validation.
4. Preserve language storage through `applyLanguage`; only replace text spans, not icon parents. Close language popover on outside/Escape; preserve focus. Trap modal focus and restore it on close. Narrow screens retain utility entries in their own row.
5. Run `.venv/bin/python -m pytest tests/test_console_contract.py -q` and Node syntax checks. Verify actual UI against isolated API server: Chinese/English, desktop/mobile/short viewport, all modal variants, success/error/empty/loading/degraded, focus and persistence. Fix any mismatch before commit.

### 3. Regression, merge and release

Files: `pyproject.toml`, `miair/const.py`, release notes as appropriate, `docs/project/CURRENT_STATE.md`, `docs/testing/castfabric-home-server-checklist.md`.

1. Inspect existing version/tag policy; choose the next alpha increment to retain current release maturity.
2. Run full `.venv/bin/python -m pytest -q`, `node --test skills/castfabric/tests/*.test.mjs`, `.venv/bin/python -m miair.miplay.probe self-test --duration 0.35`, Docker cold start and wheel asset checks. No skipped gate may be called passed.
3. Commit scoped changes (exclude unrelated untracked plans/research), push feature branch, wait for successful CI. Fetch main and check divergence before a non-destructive merge. No force push.
4. Push main and release tag; wait for publish tests, multi-architecture image and GitHub prerelease. Verify OCI revision/digest.

### 4. Home Server acceptance and handoff

1. Read-only preflight: current container/mount/config, target/suite readiness, physical playback state and active sessions. Do not stop user playback without authority; pause deployment if it would interrupt actual playback.
2. Isolated candidate cold-start and media/backfill/persistence check without physical receivers. Keep immutable accepted-image rollback and existing config mount; never run both host-network services concurrently.
3. Deploy exact release image preserving environment, mount and restart policy. Check TLS/static SVGs, bilingual UI/modal, 32 MCP tools, 20 assets and 16/4 playlist ordering/IDs/durations, all protocol readiness and no automatic playback. Restart once to confirm persistence.
4. On failure restore prior container immediately and explain evidence. On success update canonical state/checklist, commit and push handoff docs, then report release/deployment and explicitly separate silent checks from listening.

Execution continues in this task as requested. The installed `executing-plans` skill provides the available equivalent; unavailable superpowers-only helpers are replaced with the same explicit test/review/merge gates.
