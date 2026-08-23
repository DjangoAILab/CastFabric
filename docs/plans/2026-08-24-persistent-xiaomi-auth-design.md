# Persistent Xiaomi Authentication Design

## Problem

MiAir currently constructs `MiAccount` with a persistent token store and then immediately overwrites the loaded token with the `userId` and `passToken` copied from Web configuration. That discards the persisted `micoapi` service token and any rotated `passToken`. Cookie mode is then marked logged in without verification. The first Mina request can repair the state in memory, but a cold restart repeats the overwrite and may retry with a stale bootstrap token. A failed refresh removes `.mi.token`, while the application-level five-second restart policy creates an authentication storm.

## Design

Introduce an atomic, non-destructive token store and a small `PersistentMiAccount` adapter around `miservice-fork`. A complete stored token belonging to the configured user is authoritative. Web `userId`/`passToken` values are bootstrap and fallback material only. The adapter preserves the last known token when a refresh fails, restores bootstrap material when the dependency clears `account.token`, persists successful rotations with mode `0600`, and uses one stable 16-character device ID.

`AuthManager.login()` will only report success when a usable `micoapi` service token exists. When no complete stored token exists, it explicitly calls `login("micoapi")` and checks the boolean result. A newly supplied Web token is retained as a secondary recovery candidate when it differs from the stored token.

Application recovery remains inside the running process. Authentication failure keeps the Web UI available and never schedules `_restart_process`. The existing periodic health loop retries DLNA initialization with bounded exponential backoff; a healthy device response resets the backoff. This prevents tight login loops while still recovering automatically from transient Mina outages.

## Validation and recovery

Unit tests cover stored-token precedence, explicit bootstrap validation, token-file preservation, refresh fallback, and absence of process restart scheduling. Deployment validation runs the complete test suite, verifies token-file permissions without printing credentials, then performs two cold container restarts and requires Web, DLNA, and the configured speaker to recover each time. The prior image/container remains available until all gates pass.
