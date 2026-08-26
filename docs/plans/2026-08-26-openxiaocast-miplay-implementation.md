# OpenXiaoCast MiPlay Receiver Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an offline-verifiable MiPlay receiver whose decoded PCM can be played through MiAir's existing Xiaomi-speaker live audio path, then package it with reproducible Docker CI/CD.

**Architecture:** Pure Python codecs and state machines sit below an asyncio network runtime. A bundled source simulator drives the complete TCP 8899 and reverse WFD path, while a PCM sink abstraction separates wire verification from physical-speaker playback.

**Tech Stack:** Python 3.10+, asyncio, zeroconf, aiohttp, ffmpeg, pytest-compatible unittest tests, Docker Buildx, GitHub Actions.

---

### Task 1: Protocol frames and receiver identity

**Files:**
- Create: `miair/miplay/protocol.py`
- Create: `miair/miplay/mdns.py`
- Create: `miair/miplay/__init__.py`
- Test: `tests/test_miplay_protocol.py`
- Test: `tests/test_miplay_mdns.py`

**Steps:**
1. Write failing tests for `$` command frames, partial buffering, HMAC challenge response, status scalars, device-info payloads and Open URL parsing.
2. Run the focused tests and verify the missing modules fail.
3. Implement the minimal bounded codecs and validation.
4. Write failing tests for deterministic service identity, application-data encoding and scanning result parsing.
5. Implement zeroconf `ServiceInfo` creation and browsing.
6. Run the focused tests and commit.

### Task 2: Legacy receiver control session

**Files:**
- Create: `miair/miplay/control.py`
- Test: `tests/test_miplay_control.py`

**Steps:**
1. Write a transcript test covering challenge through Open.
2. Verify the test fails before implementation.
3. Implement a strict receiver state machine and response ledger.
4. Add tests for wrong HMAC, duplicate/out-of-order commands, modern Safety frames and bounded diagnostics.
5. Run focused tests and commit.

### Task 3: RTSP/WFD receiver and media decoding

**Files:**
- Create: `miair/miplay/rtsp.py`
- Create: `miair/miplay/media.py`
- Test: `tests/test_miplay_rtsp.py`
- Test: `tests/test_miplay_media.py`

**Steps:**
1. Write codec/state tests for the captured RTSP sequence.
2. Implement incremental RTSP parsing and receiver-side message generation.
3. Write tests for the `$` plus 24-bit media envelope, RTP PT 33 validation and MPEG-TS alignment.
4. Implement a bounded ffmpeg MPEG-TS-to-PCM decoder with an injectable sink.
5. Run focused tests and commit.

### Task 4: Async receiver runtime and source simulator

**Files:**
- Create: `miair/miplay/receiver.py`
- Create: `miair/miplay/simulator.py`
- Create: `miair/miplay/probe.py`
- Test: `tests/test_miplay_e2e.py`

**Steps:**
1. Write an end-to-end loopback test with ephemeral ports and a recording PCM sink.
2. Implement the TCP 8899 listener, session lifecycle and reverse three-connection WFD client.
3. Implement the deterministic source simulator and generated AAC/MPEG-TS/RTP tone stream.
4. Add `scan`, `simulate` and `self-test` CLI commands.
5. Run the end-to-end test and commit.

### Task 5: MiAir live audio integration

**Files:**
- Create: `miair/streaming/__init__.py`
- Create: `miair/streaming/sink.py`
- Modify: `miair/airplay/audio_stream.py`
- Modify: `miair/app.py`
- Modify: `miair/config.py`
- Test: `tests/test_miplay_sink.py`

**Steps:**
1. Write a fake-controller integration test for starting, writing and stopping a live stream.
2. Extract protocol-neutral configuration from `AudioStreamServer` without changing AirPlay behavior.
3. Implement `MiAirLiveAudioSink` using the configured speaker controller.
4. Start/stop one MiPlay receiver per selected gateway target and expose diagnostics.
5. Run AirPlay regression tests plus the new sink tests and commit.

### Task 6: Product naming, Docker and CI/CD

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `Dockerfile`
- Modify: `.github/workflows/build.yml`
- Create: `.github/workflows/test.yml`
- Create: `docker-compose.yml`
- Modify: `config-example.json`

**Steps:**
1. Update user-facing product text to OpenXiaoCast while retaining `miair` package compatibility.
2. Add configuration and host-network deployment documentation for MiPlay.
3. Add Python/protocol tests for pull requests.
4. Make image names repository-derived and publish only on main/version tags.
5. Build the Docker image locally and inspect its startup command and health check.
6. Run the complete test suite and commit.

### Task 7: Final verification

**Files:**
- Create: `docs/testing/miplay-real-device-checklist.md`

**Steps:**
1. Run all Python tests with the bundled Python 3 runtime.
2. Run `python -m miair.miplay.probe self-test` and retain the redacted output.
3. Build and smoke-test the Docker image.
4. Document K60 discovery, control, SafetyAuth and M01 audible-playback gates.
5. Review `git diff`, confirm no secrets or captured device identities are present, and commit locally without pushing.
