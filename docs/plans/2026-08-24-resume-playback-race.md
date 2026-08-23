# Resume Playback Race Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent false `PLAYING` state and silent M01 resumes after MiAir cache cleanup.

**Architecture:** Protect buffers referenced by active renderers in every cleanup path. Make seek creation await buffer metadata/content readiness, and make non-zero resume fail explicitly when no valid seek URL can be produced instead of silently falling back.

**Tech Stack:** Python 3.10+, asyncio, aiohttp, unittest/pytest-compatible tests, Docker.

---

### Task 1: Reproduce the races with tests

**Files:**
- Create: `tests/test_resume_playback.py`

**Steps:**
1. Add an async test where a buffer begins with `total_size == 0`, then receives headers and completed MP3 data; assert `create_seek_url()` waits and succeeds.
2. Add cleanup tests that place the current source buffer first under count and memory pressure; assert it survives.
3. Add a renderer test where resume seek generation returns `None`; assert no play command is sent and `PLAYING` is not reported.
4. Run `python3 -m unittest tests.test_resume_playback -v`; expect failures against the existing behavior.

### Task 2: Protect active source buffers

**Files:**
- Modify: `miair/dlna/device_server.py`
- Test: `tests/test_resume_playback.py`

**Steps:**
1. Add helpers that resolve protected buffer IDs from current/next renderer URIs and active proxy tasks.
2. Make TTL, count, and memory cleanup select only unprotected completed buffers.
3. Record creation timestamps for every new source buffer.
4. Run the focused cleanup tests; expect PASS.

### Task 3: Serialize resume against buffer readiness

**Files:**
- Modify: `miair/dlna/device_server.py`
- Modify: `miair/dlna/renderer.py`
- Test: `tests/test_resume_playback.py`

**Steps:**
1. Await buffer headers before validating `total_size`, then await completion before seek processing.
2. In `play()`, generate a seek URL first for non-zero resume positions; return failure if it cannot be produced.
3. Only create the normal proxy URL for playback from position zero.
4. Run focused tests; expect PASS.

### Task 4: Verify and publish source

**Files:**
- Modify as required by test findings.

**Steps:**
1. Run `python3 -m unittest discover -s tests -v` and the existing audio seek script.
2. Compile production modules with `python3 -m compileall -q miair`.
3. Review `git diff --check` and the final diff.
4. Commit and push `fix/m01-pause` to `wangerzi/MiAir`.

### Task 5: Build, deploy, and validate

**Files:**
- Remote checkout: `/home/wang/rasp-tools/home-server/MiAir`

**Steps:**
1. Fast-forward the server checkout and build an immutable image tag from the commit SHA.
2. Replace the running `miair` container while retaining the previous stopped backup container/image.
3. Verify process health, ports, Web API, DLNA description, cold restart, and sanitized logs.
4. Run a controlled buffer-cleanup/resume regression probe and confirm no `缓冲大小为0`, silent fallback, or false `播放成功` sequence.
