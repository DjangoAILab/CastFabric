# CastFabric Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert the Xiaomi-centric MiAir/OpenXiaoCast runtime into CastFabric, an open-source multi-protocol casting core with native DLNA outputs and optional vendor extensions.

**Architecture:** Preserve the working protocol servers while introducing a `PlaybackTarget` port, native DLNA discovery/output adapters, and a central router boundary. Migrate branding and configuration compatibly first, then move Xiaomi MiNA behind an optional adapter without changing existing persisted UDNs.

**Tech Stack:** Python 3.10+, asyncio, aiohttp, zeroconf, UPnP/SSDP/SOAP, ffmpeg, pytest, Docker Buildx, GitHub Actions.

---

### Task 1: Persist the product and architecture decisions

**Files:**
- Create: `docs/adr/0003-adopt-castfabric-and-port-adapter-core.md`
- Create: `docs/architecture/castfabric-system-design.md`
- Create: `docs/plans/2026-08-29-castfabric-refactor.md`

**Steps:**
1. Record the accepted CastFabric name, configurable default prefix and virtual-DLNA choice.
2. Document core/extension boundaries, failure modes, compatibility and release gates.
3. Link the ADR, design and plan and verify all paths resolve.
4. Commit the documentation independently.

### Task 2: Add CastFabric identity with backward-compatible configuration

**Files:**
- Create: `miair/identity.py`
- Modify: `miair/config.py`
- Modify: `miair/const.py`
- Modify: `miair/cli.py`
- Modify: `miair/app.py`
- Modify: `miair/dlna/ssdp.py`
- Modify: `miair/miplay/__init__.py`
- Modify: `pyproject.toml`
- Modify: `config-example.json`
- Test: `tests/test_castfabric_identity.py`
- Test: `tests/test_config_migration.py`

**Steps:**
1. Write tests asserting `CastFabric` defaults and preservation of explicitly customized legacy names.
2. Run the focused tests and verify they fail.
3. Add product constants and `device_name_prefix`; treat the legacy default `OpenXiaoCast` as migratable.
4. Add `castfabric` and `castfabric-miplay` CLI entries while keeping old commands.
5. Use the product identity in logs, SSDP server headers and MiPlay identity generation.
6. Run focused and full tests, then commit.

### Task 3: Introduce the output target port and adapters

**Files:**
- Create: `miair/outputs/__init__.py`
- Create: `miair/outputs/base.py`
- Create: `miair/outputs/dlna.py`
- Create: `miair/outputs/xiaomi.py`
- Modify: `miair/speaker.py`
- Modify: `miair/streaming/sink.py`
- Modify: `miair/airplay/speaker_airplay.py`
- Test: `tests/test_output_targets.py`
- Test: `tests/test_speaker_play_url.py`

**Steps:**
1. Write contract tests for play, pause, stop, volume and status.
2. Verify the missing output modules fail.
3. Define `PlaybackTarget`, typed status and capability metadata without importing Xiaomi code.
4. Wrap `LocalDLNAClient` and MiNA behavior in separate adapters.
5. Make the legacy `SpeakerController` a compatibility facade over a prioritized adapter chain.
6. Run protocol and controller regressions, then commit.

### Task 4: Discover and persist generic DLNA targets

**Files:**
- Modify: `miair/dlna/client.py`
- Modify: `miair/config.py`
- Create: `miair/targets.py`
- Test: `tests/test_dlna_target_discovery.py`
- Test: `tests/test_target_config.py`

**Steps:**
1. Write fixture-based tests for multiple SSDP responses, UDN normalization, description parsing and deduplication.
2. Implement generic MediaRenderer discovery and cached-location validation.
3. Add target configuration keyed by stable target ID.
4. Migrate legacy speaker cache to a compatibility target without deleting old fields.
5. Verify discovery works with no account, cookie or `mi_did`, then commit.

### Task 5: Separate service orchestration from Xiaomi authentication

**Files:**
- Create: `miair/router.py`
- Modify: `miair/app.py`
- Modify: `miair/dlna/renderer.py`
- Modify: `miair/airplay/speaker_airplay.py`
- Modify: `miair/miplay/receiver.py`
- Test: `tests/test_router.py`
- Test: `tests/test_app_without_xiaomi.py`

**Steps:**
1. Write tests proving a configured DLNA target starts every enabled ingress without constructing `AuthManager` as a prerequisite.
2. Implement serialized session ownership and diagnostics in `CastRouter`.
3. Start Web and target discovery independently; start protocol ingress from enabled targets.
4. Keep authentication recovery inside the optional Xiaomi extension lifecycle.
5. Verify one failed ingress does not clear other registrations, then commit.

### Task 6: Expose LAN target selection and migration state in Web UI

**Files:**
- Modify: `miair/web/api.py`
- Modify: `miair/web/static/index.html`
- Test: `tests/test_web_targets.py`

**Steps:**
1. Write API tests for target scanning, selection, masked extension credentials and independent health states.
2. Add `/api/targets` discovery and persisted selection endpoints.
3. Change the primary setup flow from Xiaomi login to LAN renderer selection.
4. Move Xiaomi account settings into an “optional extensions” section.
5. Display separate ingress, output, discovery and extension status.
6. Run API tests and inspect the UI at mobile and desktop widths, then commit.

### Task 7: Complete branding, packaging and migration-safe CI/CD

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `deploy.sh`
- Modify: `manage.sh`
- Modify: `.github/workflows/test.yml`
- Modify: `.github/workflows/build.yml`
- Create: `docs/migration/miair-to-castfabric.md`

**Steps:**
1. Replace user-facing product strings and set the default service/container/image example to `castfabric`.
2. Preserve the old config mount and commands as documented aliases for one migration release.
3. Ensure CI runs tests and an offline MiPlay self-test before multi-architecture publication.
4. Build the image locally and verify OCI title/source labels and health check.
5. Test cold start with a new config and upgrade with an old config fixture.
6. Run a secret scan and complete suite, then commit.

### Task 8: Home Server deployment and real-device gates

**Files:**
- Modify: `docs/testing/miplay-real-device-checklist.md`
- Create: `docs/testing/castfabric-home-server-checklist.md`

**Steps:**
1. Build a commit-addressed Docker image and deploy it with the existing persistent config.
2. Verify Web health, SSDP responses, AirPlay mDNS and MiPlay mDNS before phone testing.
3. Confirm both the physical renderer and `CastFabric · <target>` remain discoverable.
4. Test DLNA direct, virtual DLNA, AirPlay and MiPlay play/pause/volume in sequence.
5. Invalidate or disable Xiaomi authentication and repeat all standard-DLNA gates.
6. Capture redacted latency/diagnostic results and define rollback conditions.
7. Push focused commits only after local and Home Server gates pass.

