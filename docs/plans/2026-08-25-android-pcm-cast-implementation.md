# MiAir Cast Android PCM Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an Android app that captures permitted system media audio as PCM and streams it over the home LAN to MiAir, which exposes the PCM as a live WAV stream to one configured M01 speaker.

**Architecture:** The Android app owns MediaProjection consent, AudioRecord capture, foreground-service lifetime, and a versioned PCM WebSocket client. MiAir owns pairing, one active PCM session, jitter/backpressure handling, the live WAV endpoint, and truthful speaker-connected state based on the M01 HTTP request rather than the MiNA command acknowledgement.

**Tech Stack:** Kotlin, Jetpack Compose, Android AudioPlaybackCapture/AudioRecord, OkHttp WebSocket, Python 3.10+, aiohttp, asyncio, existing MiAir SpeakerController and live WAV code.

---

## Preconditions

- Work from a dedicated feature worktree/branch based on `fix/m01-pause` commit `3cc954b` or its reviewed successor.
- Keep the Android app under `android/` in the same repository until the protocol stabilizes.
- Use package name `io.github.wangerzi.miair.cast` and app label `MiAir Cast`.
- Do not modify Xiaomi authentication, DLNA pause/resume, or cookie masking behavior.
- Do not store PCM in logs, files, crash reports, fixtures, or diagnostic exports.
- Read `docs/plans/2026-08-25-android-pcm-cast-design.md` and `docs/adr/0001-use-audioplaybackcapture-for-android-pcm.md` before implementation.

### Task 1: Establish the shared PCM protocol contract

**Files:**
- Create: `miair/pcm/__init__.py`
- Create: `miair/pcm/protocol.py`
- Create: `tests/test_pcm_protocol.py`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/protocol/PcmFrame.kt`
- Create: `android/app/src/test/java/io/github/wangerzi/miair/cast/protocol/PcmFrameTest.kt`

**Step 1: Write Python failing tests**

Cover a valid 20 ms stereo frame, invalid magic, unsupported version, inconsistent payload length,
non-monotonic sequence, EOS without payload, and a maximum payload guard. Use generated zero/sample
bytes in memory; do not commit recorded audio.

**Step 2: Run the focused test**

Run: `python3 -m pytest tests/test_pcm_protocol.py -q`  
Expected: FAIL because `miair.pcm.protocol` does not exist.

**Step 3: Implement the Python codec**

Define immutable `PcmFrameHeader`, `PcmFormat`, `PcmFlags`, `ProtocolError`,
`encode_header()` and `decode_frame()`. Use big-endian network order for header integers and leave
PCM payload little-endian. Reject channels other than 2, sample rates other than 48000, and formats
other than PCM S16LE in protocol version 1.

**Step 4: Run Python tests**

Run: `python3 -m pytest tests/test_pcm_protocol.py -q`  
Expected: PASS.

**Step 5: Add the equivalent Kotlin codec and golden-vector test**

Use a committed hexadecimal golden vector generated from Python. Kotlin must encode the exact same
header and decode the expected fields without copying any PCM fixture to disk.

**Step 6: Run Android unit tests**

Run: `cd android && ./gradlew testDebugUnitTest --tests '*PcmFrameTest'`  
Expected: PASS.

**Step 7: Commit**

```bash
git add miair/pcm tests/test_pcm_protocol.py android
git commit -m "feat: define MiAir PCM wire protocol"
```

### Task 2: Scaffold the Android application and four-state UI

**Files:**
- Create: `android/settings.gradle.kts`
- Create: `android/build.gradle.kts`
- Create: `android/gradle/libs.versions.toml`
- Create: `android/app/build.gradle.kts`
- Create: `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/MainActivity.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/ui/AppState.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/ui/MiAirCastApp.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/ui/theme/Theme.kt`
- Create: `android/app/src/androidTest/java/io/github/wangerzi/miair/cast/ui/AppStateTest.kt`

**Step 1: Create a minimal Compose project**

Set `minSdk = 29`; choose the current installed stable compile/target SDK at implementation time.
Add only Compose, lifecycle, coroutines, DataStore, security-crypto if still supported, and OkHttp.
Do not introduce navigation or dependency-injection frameworks until a second real navigation need appears.

**Step 2: Write UI tests for the four product states**

Assert exact visible primary text and actions for `Onboarding`, `Ready`, `Streaming`, and
`NoCapturableAudio`. Use the checked-in prototype as visual intent, not a pixel-golden dependency.

**Step 3: Run tests to verify failure**

Run: `cd android && ./gradlew connectedDebugAndroidTest`  
Expected: FAIL because the screens are missing.

**Step 4: Implement the static Compose screens**

Match `docs/product/mi-air-cast-prototype.png`. Keep one primary action per state. Do not add album
art, song metadata, notification-listener permission, microphone controls, or a fake play/pause button.

**Step 5: Add accessibility semantics**

Provide content descriptions for connection state and waveform; expose state by text as well as color;
ensure warning actions are reachable without relying on amber alone.

**Step 6: Run UI tests and lint**

Run: `cd android && ./gradlew testDebugUnitTest lintDebug connectedDebugAndroidTest`  
Expected: PASS.

**Step 7: Commit**

```bash
git add android
git commit -m "feat: scaffold MiAir Cast Android experience"
```

### Task 3: Add pairing credentials and service discovery

**Files:**
- Create: `miair/pcm/pairing.py`
- Create: `tests/test_pcm_pairing.py`
- Modify: `miair/config.py`
- Modify: `miair/web/api.py`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/pairing/PairingRepository.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/discovery/MiAirDiscovery.kt`
- Create: `android/app/src/test/java/io/github/wangerzi/miair/cast/pairing/PairingRepositoryTest.kt`

**Step 1: Write server tests for pairing lifecycle**

Test short-lived one-time code creation, successful exchange for a random 256-bit token, expiry,
single use, constant-time token verification, revocation, and masked API output.

**Step 2: Run the failing tests**

Run: `python3 -m pytest tests/test_pcm_pairing.py -q`  
Expected: FAIL because pairing support is absent.

**Step 3: Implement pairing storage**

Store only a salted token hash and metadata in MiAir config. Never return a saved token from the Web
settings API. Pairing permissions must be limited to PCM session creation, PCM upload, session status,
and target-speaker volume.

**Step 4: Add pairing endpoints**

- `POST /api/pcm/pairing-code` from the authenticated/local Web UI context.
- `POST /api/pcm/pair` with code and client label.
- `DELETE /api/pcm/clients/{client_id}` for revocation.

Rate-limit code creation and exchange in memory. Do not reuse Xiaomi login credentials.

**Step 5: Implement Android persistence and discovery**

Discover `_miair-pcm._tcp.local` with NSD, retain a manual host fallback, and store the token using
Android Keystore-backed encryption. Never print it in Logcat.

**Step 6: Run tests**

Run: `python3 -m pytest tests/test_pcm_pairing.py -q`  
Run: `cd android && ./gradlew testDebugUnitTest`  
Expected: PASS.

**Step 7: Commit**

```bash
git add miair/config.py miair/web/api.py miair/pcm tests android
git commit -m "feat: pair Android clients with MiAir"
```

### Task 4: Implement the MiAir PCM session and jitter buffer

**Files:**
- Create: `miair/pcm/jitter_buffer.py`
- Create: `miair/pcm/session.py`
- Create: `tests/test_pcm_jitter_buffer.py`
- Create: `tests/test_pcm_session.py`

**Step 1: Write jitter-buffer tests**

Cover ordered frames, a small timestamp gap filled with silence, duplicates, stale frames, large gaps
marked as discontinuities, bounded memory, producer faster than consumer, and oldest-frame dropping.

**Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_pcm_jitter_buffer.py tests/test_pcm_session.py -q`  
Expected: FAIL because the components are absent.

**Step 3: Implement a bounded single-producer/single-consumer buffer**

Default target is 120 ms, minimum 80 ms, maximum 500 ms. Store only in-memory PCM chunks. Expose
queue duration, dropped frames, inserted silence, last sequence, last PCM timestamp, and idle duration.

**Step 4: Implement the session state machine**

Use explicit states from the design document. Permit one active session. Separate these facts:
`receiving_pcm`, `speaker_command_accepted`, `speaker_http_connected`, and `streaming`.

**Step 5: Run tests**

Run: `python3 -m pytest tests/test_pcm_jitter_buffer.py tests/test_pcm_session.py -q`  
Expected: PASS with no task-leak warnings.

**Step 6: Commit**

```bash
git add miair/pcm tests/test_pcm_jitter_buffer.py tests/test_pcm_session.py
git commit -m "feat: buffer and track live PCM sessions"
```

### Task 5: Extract a reusable live PCM/WAV stream

**Files:**
- Create: `miair/streaming/__init__.py`
- Create: `miair/streaming/live_pcm.py`
- Modify: `miair/airplay/audio_stream.py`
- Create: `tests/test_live_pcm_stream.py`

**Step 1: Write WAV-stream tests**

Use an aiohttp test client to verify a valid streaming WAV header, PCM byte order, HTTP client-connected
callback, cancellation, EOS, idle timeout, and rejection after stop. Ensure no entire-stream buffering.

**Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_live_pcm_stream.py -q`  
Expected: FAIL because `LivePcmStream` is absent.

**Step 3: Implement `LivePcmStream`**

Accept an async chunk source and expose a unique uncacheable HTTP URL. Use the existing large WAV data
length convention, `audio/wav`, chunked transfer, `TCP_NODELAY`, and an explicit client-connected event.

**Step 4: Refactor AirPlay without behavior change**

Make AirPlay use the shared primitive or its common header/writer helpers. Preserve current AirPlay URL,
stop semantics, queue behavior, and M01 fixes. Run existing AirPlay/DLNA tests after every extraction.

**Step 5: Run tests**

Run: `python3 -m pytest tests/test_live_pcm_stream.py tests/test_audio_seek.py tests/test_resume_playback.py -q`  
Expected: PASS.

**Step 6: Commit**

```bash
git add miair/streaming miair/airplay/audio_stream.py tests/test_live_pcm_stream.py
git commit -m "refactor: share the live PCM WAV stream"
```

### Task 6: Expose authenticated PCM WebSocket and truthful status

**Files:**
- Create: `miair/pcm/api.py`
- Modify: `miair/app.py`
- Modify: `miair/web/api.py`
- Create: `tests/test_pcm_api.py`

**Step 1: Write API tests**

Test unauthorized rejection, session creation, second-session conflict, binary-only WebSocket frames,
invalid-frame closure, status before/after PCM, status before/after WAV HTTP GET, EOS, stop, timeout,
and absence of payload bytes in captured logs.

**Step 2: Run failing tests**

Run: `python3 -m pytest tests/test_pcm_api.py -q`  
Expected: FAIL because routes are absent.

**Step 3: Wire the session manager into `MiAir`**

Create it after the Web app and speaker manager are available. Stop all sessions before restarting DLNA
or replacing SpeakerController instances. A config/auth restart must not leave a stale stream URL alive.

**Step 4: Add API routes**

- `POST /api/pcm/sessions`
- `GET /api/pcm/sessions/{id}`
- `GET /api/pcm/sessions/{id}/audio` as WebSocket
- `DELETE /api/pcm/sessions/{id}`
- `PUT /api/pcm/sessions/{id}/volume`

Return stable machine-readable error codes plus Chinese user messages. Never report `streaming=true`
until the speaker has opened the live WAV endpoint.

**Step 5: Run tests**

Run: `python3 -m pytest tests/test_pcm_api.py tests/test_auth_persistence.py tests/test_speaker_pause.py -q`  
Expected: PASS.

**Step 6: Commit**

```bash
git add miair/app.py miair/web/api.py miair/pcm tests/test_pcm_api.py
git commit -m "feat: receive authenticated Android PCM sessions"
```

### Task 7: Implement Android audio capture and foreground lifetime

**Files:**
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/capture/CaptureConfig.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/capture/PcmCapture.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/service/CastService.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/service/CastNotification.kt`
- Create: `android/app/src/test/java/io/github/wangerzi/miair/cast/capture/CaptureConfigTest.kt`
- Create: `android/app/src/androidTest/java/io/github/wangerzi/miair/cast/capture/ProjectionLifecycleTest.kt`
- Modify: `android/app/src/main/AndroidManifest.xml`

**Step 1: Add permissions and service declarations**

Declare `RECORD_AUDIO`, `INTERNET`, `ACCESS_NETWORK_STATE`, foreground service, media-projection service
type, notifications where required, and Wi-Fi multicast only if NSD testing proves it necessary. Do not
request microphone input, accessibility, notification listener, storage, contacts, or location.

**Step 2: Write lifecycle tests**

Cover permission denied, projection granted, projection callback stop, AudioRecord initialization
failure, client disconnect, service stop action, and no automatic re-prompt.

**Step 3: Implement capture**

Match MEDIA/GAME/UNKNOWN usages. Request 48 kHz, stereo, PCM 16-bit. Read into preallocated 20 ms
buffers on a dedicated thread. Emit RMS/peak metrics separately from PCM frames. Never write audio to disk.

**Step 4: Implement the foreground service**

Own the MediaProjection, AudioRecord, network client, wake/Wi-Fi lock only while needed, notification,
and deterministic cleanup. App UI binds to a `StateFlow`; the service remains authoritative.

**Step 5: Run tests**

Run: `cd android && ./gradlew testDebugUnitTest connectedDebugAndroidTest lintDebug`  
Expected: PASS.

**Step 6: Commit**

```bash
git add android
git commit -m "feat: capture Android media audio as PCM"
```

### Task 8: Implement Android transport, state reconciliation, and UX

**Files:**
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/network/MiAirApi.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/network/PcmWebSocket.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/session/CastSession.kt`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/session/CastViewModel.kt`
- Create: `android/app/src/test/java/io/github/wangerzi/miair/cast/session/CastSessionTest.kt`
- Modify: `android/app/src/main/java/io/github/wangerzi/miair/cast/ui/MiAirCastApp.kt`

**Step 1: Write session reconciliation tests**

Test transitions for capture-without-network, PCM-without-speaker, speaker connected, silence longer than
five seconds, bounded reconnect, server busy, explicit stop, and stale status response.

**Step 2: Implement the REST/WebSocket client**

Attach the scoped bearer token, validate response IDs, send binary frames only, cap the outgoing queue,
and drop oldest frames on backpressure with the discontinuity flag. Never retry authentication failure.

**Step 3: Implement truthful product state**

Map the three independent stages to UI. `MiAir 已连接` is not `正在投送`; `play_by_url` accepted is not
`音箱已连接`; zero RMS is not a network error.

**Step 4: Add volume and stop**

Debounce volume writes and make stop idempotent. Source playback remains in the source App.

**Step 5: Run tests**

Run: `cd android && ./gradlew testDebugUnitTest connectedDebugAndroidTest lintDebug`  
Expected: PASS.

**Step 6: Commit**

```bash
git add android
git commit -m "feat: stream PCM and expose truthful cast state"
```

### Task 9: Add observability, diagnostics, and privacy checks

**Files:**
- Create: `miair/pcm/metrics.py`
- Create: `tests/test_pcm_privacy.py`
- Create: `android/app/src/main/java/io/github/wangerzi/miair/cast/diagnostics/SessionDiagnostics.kt`
- Create: `android/app/src/test/java/io/github/wangerzi/miair/cast/diagnostics/SessionDiagnosticsTest.kt`
- Modify: `miair/web/static/index.html`

**Step 1: Define safe metrics**

Include session ID prefix, state, duration, byte/frame counts, queue milliseconds, drops, inserted silence,
last activity age, speaker HTTP-connected boolean, start timings, and error code. Exclude token, PCM,
Xiaomi cookie, full DID/device ID, source App content, and media metadata.

**Step 2: Add privacy regression tests**

Feed a unique binary marker as PCM and assert it is absent from logs, JSON status, exceptions, and
diagnostic export. Assert pairing tokens and Xiaomi credentials remain masked.

**Step 3: Add Web UI client management**

Show paired client label, last-seen time, active state, and revoke action. Generate pairing code/QR without
placing secrets in browser console logs or persistent HTML.

**Step 4: Run tests**

Run: `python3 -m pytest tests/test_pcm_privacy.py tests/test_pcm_api.py tests/test_auth_persistence.py -q`  
Run: `cd android && ./gradlew testDebugUnitTest lintDebug`  
Expected: PASS.

**Step 5: Commit**

```bash
git add miair/pcm miair/web/static/index.html tests android
git commit -m "feat: diagnose PCM sessions without retaining audio"
```

### Task 10: Integrate, package, deploy, and validate on the real M01

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/docker.yml` only if Android artifacts are intentionally added to CI
- Create: `docs/testing/android-pcm-m01-validation.md`
- Create: `android/README.md`

**Step 1: Run all existing server regression tests**

Use the repository's Python 3.10+ environment. Run every current focused test script plus the new PCM
tests. Expected: all deterministic tests pass; ffmpeg-dependent skips remain documented.

**Step 2: Build the Android debug APK**

Run: `cd android && ./gradlew assembleDebug lintDebug testDebugUnitTest`  
Expected: `app-debug.apk`, clean lint or explicitly reviewed baseline.

**Step 3: Build a new MiAir image without replacing the healthy container**

Build a versioned image tag. Start a separate bounded test instance only if ports and Xiaomi account
semantics permit; otherwise schedule a controlled replacement with the current config volume preserved.
Record the previous known-good image tag for rollback.

**Step 4: Execute the Phase 0 real-device matrix**

- 5-minute channel/sine/sweep test.
- 30-minute music stability test.
- YouTube/local-video latency observation.
- Screen off/on, source pause/resume, Wi-Fi switch, projection revoke.
- Target App that permits capture and one that refuses it.
- M01 voice interruption and competing playback.

Record capture-to-server latency separately from server-to-audible latency. Do not claim bit-perfect or
lip-sync performance without measurements.

**Step 5: Verify privacy and cleanup**

Search container logs, Android Logcat, config, app storage, and diagnostics for the unique PCM marker and
tokens. Expected: no PCM or plaintext credentials persisted.

**Step 6: Document results and rollback**

Fill `docs/testing/android-pcm-m01-validation.md` with firmware/hardware identity, network conditions,
build commits, metrics, failures, and the exact rollback image. Mark the feature experimental until the
30-minute run and recovery matrix pass.

**Step 7: Commit and push**

```bash
git add README.md android/README.md docs/testing
git commit -m "docs: validate Android PCM casting on M01"
git push origin HEAD
```

## Completion Gate

The MVP is complete only when all of the following are true:

- The K60 starts a capture session after explicit system consent.
- Allowed media produces PCM; a blocked App produces an actionable limitation state.
- MiAir distinguishes PCM reception from M01 HTTP connection.
- The M01 plays continuously for 30 minutes on stable Wi-Fi without a repeatable audible gap.
- Stop, projection revoke, network loss, and competing playback release all resources deterministically.
- No PCM or plaintext pairing/Xiaomi credential appears in logs or persistent storage.
- A known-good MiAir image remains available for rollback.

