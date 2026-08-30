# CastFabric Runtime v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace global/default-target runtime state with one independently managed Receiver Suite per enabled output and expose the verified v6 console through safe collection APIs.

**Architecture:** Introduce pure domain/read-model components beside the existing protocol servers, register existing DLNA and AirPlay instances first, then replace the single MiPlay receiver with a per-target registry. New `/api/v1` endpoints consume only the read models; the old API and compatibility properties remain for one migration release.

**Tech Stack:** Python 3.10+, asyncio, aiohttp, zeroconf, dataclasses, bounded deque/JSONL, static HTML/CSS/JavaScript, pytest, Docker/GitHub Actions.

---

### Task 1: Add typed runtime models and privacy projection

**Files:**
- Create: `miair/runtime/models.py`
- Create: `miair/runtime/redaction.py`
- Create: `miair/runtime/__init__.py`
- Test: `tests/test_runtime_models.py`
- Test: `tests/test_runtime_redaction.py`

**Steps:**
1. Write failing tests for OutputTarget, Ingress, Suite, Session and Event snapshots and enum serialization.
2. Write failing redaction tests containing Cookie-like keys, full IPs and media URLs with query tokens.
3. Implement frozen snapshot dataclasses and explicit `to_dict()` methods; never serialize arbitrary `__dict__`.
4. Implement allowlist-based event detail redaction and location host projection.
5. Run focused tests, then the full suite; commit `feat: add CastFabric runtime read models`.

### Task 2: Add discovery lifecycle and target migration fields

**Files:**
- Modify: `miair/targets.py`
- Modify: `miair/config.py`
- Create: `miair/runtime/discovery.py`
- Test: `tests/test_target_config.py`
- Create: `tests/test_target_discovery_registry.py`

**Steps:**
1. Add tests for `receiver_alias`, legacy default-target read compatibility and no new default writes.
2. Add tests proving scan start retains the previous snapshot, concurrent scans return busy, and errors retain observations.
3. Implement `TargetDiscoveryRegistry` with a single scan task, immutable observations and timestamps.
4. Add target alias migration without deleting legacy fields.
5. Verify scanning never depends on Xiaomi auth; commit `feat: add target discovery registry`.

### Task 3: Add per-target session coordination and structured journal

**Files:**
- Create: `miair/runtime/sessions.py`
- Create: `miair/runtime/events.py`
- Test: `tests/test_media_sessions.py`
- Test: `tests/test_activity_events.py`

**Steps:**
1. Test same-target preemption, different-target parallel sessions and stale callback rejection.
2. Test bounded event queries, target/protocol/outcome filters and stable cursor ordering.
3. Test JSONL rotation and write-failure degradation without playback exceptions.
4. Implement `MediaSessionCoordinator` with one lock/current owner per target.
5. Implement `ActivityEventJournal` with a 500-event deque and redacted JSONL writes.
6. Run focused/full tests; commit `feat: add media sessions and activity journal`.

### Task 4: Introduce Receiver Suite registry around existing DLNA and AirPlay

**Files:**
- Create: `miair/runtime/suites.py`
- Modify: `miair/speaker.py`
- Modify: `miair/app.py`
- Modify: `miair/dlna/ssdp.py`
- Modify: `miair/dlna/device_server.py`
- Modify: `miair/airplay/speaker_airplay.py`
- Test: `tests/test_receiver_suites.py`
- Modify: `tests/test_app_without_xiaomi.py`

**Steps:**
1. Test stable target-to-controller mapping and suite snapshots for two targets.
2. Add unregister methods to shared DLNA servers and per-speaker stop to AirPlayManager.
3. Register existing renderer/AirPlay objects under target IDs without changing their protocol behavior.
4. Implement transactional single-suite enable/disable with rollback.
5. Inject one AirPlay startup failure and prove both DLNA suites remain.
6. Run protocol/full tests; commit `feat: manage receiver suites per output`.

### Task 5: Replace the global MiPlay receiver with isolated instances

**Files:**
- Modify: `miair/app.py`
- Modify: `miair/miplay/receiver.py`
- Modify: `miair/streaming/sink.py`
- Modify: `miair/runtime/suites.py`
- Modify: `tests/test_miplay_app.py`
- Create: `tests/test_miplay_multi_target.py`

**Steps:**
1. Write a two-target test asserting unique identity, name, port and controller binding.
2. Test port overflow/port collision degrades one ingress only.
3. Add receiver lifecycle callbacks that emit session and event transitions without source-App guessing.
4. Store `miplay_receivers[target_id]`; retain `miplay_receiver` as read-only first-item compatibility.
5. Verify stop cleans every receiver and existing MiPlay e2e tests pass.
6. Commit `feat: isolate MiPlay receivers per output`.

### Task 6: Expose safe collection APIs

**Files:**
- Create: `miair/web/api_v1.py`
- Modify: `miair/web/api.py`
- Create: `tests/test_api_v1.py`
- Create: `tests/fixtures/console_contract.json`

**Steps:**
1. Write schema assertions for system, targets, suites, sessions, events and settings responses.
2. Test scan concurrency, target patch allowlists, independent toggle rollback and typed errors.
3. Test settings responses never include account/password/cookie or legacy default target.
4. Implement `/api/v1` handlers using runtime projectors only.
5. Add diagnostics export with redaction and bounded files.
6. Run API/full tests; commit `feat: add CastFabric console API v1`.

### Task 7: Connect the accepted v6 production console

**Files:**
- Modify: `miair/web/static/index.html`
- Create: `miair/web/static/console.js`
- Create: `miair/web/static/console.css`
- Modify: `docs/prototypes/validate_console_prototype.py`
- Create: `tests/test_console_contract.py`

**Steps:**
1. Extract approved v6 structure without review-only controls or fixed demo rows.
2. Render only API v1 fields registered in the machine contract; apply every documented fallback.
3. Wire navigation, independent target edit/toggle, scan, filters, settings and language preference.
4. Add loading/empty/degraded/error fixtures and API failure tests.
5. Run Playwright at desktop/mobile and Chinese/English, then inspect screenshots.
6. Commit `feat: ship CastFabric v6 console`.

### Task 8: Complete migration, CI and offline release gates

**Files:**
- Modify: `config-example.json`
- Modify: `docs/migration/miair-to-castfabric.md`
- Modify: `docs/testing/2026-08-26-offline-validation.md`
- Modify: `.github/workflows/test.yml`
- Modify: `.github/workflows/build.yml`
- Create: `tests/test_runtime_v2_migration.py`

**Steps:**
1. Test old config cold start, upgraded save, rollback load and second upgrade.
2. Verify no new code chooses `default_target_id` and v1 never exposes it.
3. Add two-target fake-DLNA integration and offline MiPlay probes to CI.
4. Run full tests, secret scan, Docker build and container health probe.
5. Commit `ci: gate CastFabric runtime v2 release`.

### Task 9: Deploy and validate on Home Server

**Files:**
- Modify: `docs/testing/castfabric-home-server-checklist.md`
- Modify: `docs/roadmap/2026-08-30-castfabric-product-to-implementation-roadmap.md`

**Steps:**
1. Deploy a commit-addressed image while preserving `/app/conf` and the rollback image.
2. Verify API health, target snapshots and every enabled suite before phone testing.
3. Verify physical DLNA plus each CastFabric DLNA/AirPlay/MiPlay advertisement.
4. Test play/pause/volume, same-target takeover and two-target parallel playback.
5. Disable Xiaomi extension and repeat core gates.
6. Record redacted results, promote or immediately rollback, then commit final documentation.
