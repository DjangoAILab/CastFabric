# Persistent Xiaomi Authentication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Xiaomi Mina authentication survive restarts and refresh failures without repeated manual token maintenance or restart storms.

**Architecture:** Preserve complete service tokens in an atomic token store and use Web credentials only as bootstrap/fallback material. Wrap `miservice-fork` account behavior to retain refresh credentials, and retry failed authentication inside the running application with bounded backoff.

**Tech Stack:** Python 3.12, asyncio, aiohttp, miservice-fork, unittest, Docker.

---

### Task 1: Lock in the authentication failures

**Files:**
- Create: `tests/test_auth_persistence.py`
- Create: `tests/test_auth_recovery.py`

**Steps:**
1. Test that an existing matching `micoapi` token survives `AuthManager.login()` unchanged.
2. Test that cookie bootstrap explicitly calls `login("micoapi")` and respects a false return.
3. Test that failed refresh does not delete the last persisted token and can try a newer bootstrap candidate.
4. Test that empty device discovery does not schedule a process restart.
5. Run focused tests against the old implementation and record expected failures.

### Task 2: Implement persistent token lifecycle

**Files:**
- Modify: `miair/auth.py`
- Test: `tests/test_auth_persistence.py`

**Steps:**
1. Add atomic token loading/saving with `0600` permissions and non-destructive failed saves.
2. Add a persistent account adapter that preserves refresh candidates and stable device ID.
3. Prefer a complete matching stored token and explicitly validate incomplete bootstrap state.
4. Run focused tests and expect PASS.

### Task 3: Replace restart storms with in-process recovery

**Files:**
- Modify: `miair/app.py`
- Test: `tests/test_auth_recovery.py`

**Steps:**
1. Remove authentication-triggered process restart calls.
2. Retry device discovery and DLNA initialization with bounded exponential backoff.
3. Keep Web state available and reset backoff after recovery.
4. Run focused tests and expect PASS.

### Task 4: Verify and publish

**Files:**
- Review all modified production and test files.

**Steps:**
1. Run all unittest and existing audio-seek tests in Python 3.12.
2. Compile production modules and run `git diff --check`.
3. Confirm logs and tests never expose credential values.
4. Commit and push `fix/m01-pause` to the user's Fork.

### Task 5: Deploy and cold-restart validate

**Files:**
- Remote checkout: `/home/wang/rasp-tools/home-server/MiAir`

**Steps:**
1. Build an immutable image tagged with the commit SHA and run tests inside it.
2. Deploy with the existing persistent configuration mount and retain the prior container.
3. Bootstrap a current browser token only if the preserved token cannot recover; credential entry remains a user handoff.
4. Require two consecutive cold restarts to recover Web, DLNA, and the configured M01 speaker.
5. Restore automatic fault handling and verify bounded retry behavior.
