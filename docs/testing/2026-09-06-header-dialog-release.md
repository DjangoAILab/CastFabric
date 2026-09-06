# Approved header/dialog and alpha.4 verification

User approval: 2026-09-06, recommended A direction. See the dated design study and implementation plan.

## Local implementation gates

- New regression tests initially failed for MP3 duration, old-file backfill, unknown totals, missing canonical SVG and missing scoped dialog centering; they pass after implementation.
- Full Python suite: 231 passed. Five Node helper tests and offline MiPlay wire self-test passed.
- Real isolated aiohttp/SQLite console on loopback (no receivers/discovery): create by Enter, edit playlist, URL resource create/edit, actual MP3 upload and resource selection all passed. The uploaded Sleep file reports 3:04; URL query parameters are redacted.
- Chinese and English utility labels and SVGs survive language changes/reload. Direct `#content` navigation now opens the content page.
- Desktop 1440×900 and mobile 390×844: content dialogs are centered, no page horizontal overflow. At 390×500, dialog spans y=16..484, body scrolls, footer remains inside viewport.
- Empty-name validation remains inline; failed API request preserves draft and shows a retryable error. Empty/loading/error states use real API results or explicit network failure injection, not claims based on fixtures alone.
- Content modal autofocus targets the first field; Tab wraps within the dialog, background is inert, Escape restores the trigger. Existing connection-settings and drawer layouts are not repositioned by the scoped centering rule.
- Added no-speaker empty state; resource source-filter options and Retry are bilingual. Two track actions have dedicated width, and multi-action edit-dialog footers wrap on narrow screens.
- No production play, pause, stop, volume or restart command was sent during local verification.
- Real delayed API startup renders the loading state before awaiting the network. At 320px English
  utilities stay within the viewport; at 1024px, navigation and utilities occupy distinct rows.
- Final-source Docker image passes cold start, installed-wheel static-asset checks, 32-tool MCP
  discovery/read-only call, and restart without autoplay. A disposable one-second MP3 fixture starts
  with unknown duration, backfills to 1.0 seconds and retains its resource ID, playlist ID/revision,
  metadata and six-table schema across restart. Only disposable test containers/volumes were removed.

## Merge and CI evidence

- Final feature commit: `0bbcc48a5cb95303100b7dc1f5fd0cc53ebb8458`; feature CI `34032135796`
  passed all Python, Node, offline MiPlay and container gates.
- Merged to main as `d6e7a076ad325c4800562c27f9df400f79c8909c`, with the exact tested feature
  tree. Main and annotated `v0.11.0-alpha.4` were pushed atomically, without rewriting history.
- Main publication run `34032487886` passed its Python suite. Tag run `34032488040` attempt 1
  failed only the existing `test_complete_miplay_wire_reaches_live_http_stream` byte-count timing
  assertion: 17,964 bytes versus a threshold of 19,244. Handshake, WAV pull and nonzero PCM passed.
  Ten immediate local repetitions of that unchanged test passed. No protocol code or assertion was
  changed to conceal the failure. Attempt 2 passed the full Python, Node and offline MiPlay job;
  the original Docker job also passed. Publication then proceeded normally.

## Release / deployment status

Tag run `34032488040` attempt 2 and main run `34032487886` both completed successfully.
GitHub prerelease `v0.11.0-alpha.4` was published at `2026-09-06T12:43:05Z`; its body uses the
checked-in release notes. Both AMD64 and ARM64 manifests are present.

- Immutable OCI index: `sha256:68c889784f2e0fc59ca3b11593f227a55122e6bebb5caf39e2b5235a63ecd38a`.
- AMD64 manifest: `sha256:4e6ce8ca0bf0a75470918f0aea2f3a1ce2162535abada97920703bc12eea43f5`.
- Home Server image ID: `sha256:fb2dee9e7970ee58e9c463a2dcfebeea5cc182422d0cce6ce841dfe464859369`.
- Image revision matches merge commit `d6e7a076ad325c4800562c27f9df400f79c8909c` exactly.
- Published-image isolated Home Server gates passed: one-second legacy MP3 duration backfill,
  unchanged resource/playlist IDs and revision, cold start/restart, 32 MCP tools and offline MiPlay.
  The isolated test container and named volume were removed; production media was not deleted.

## Home Server rollout and acceptance

The user explicitly confirmed deployment and acceptance after the earlier playback gate. New
preflight reported stopped playback and volume 0; no play, stop or volume command was necessary.
The first production start was `2026-09-06T14:13:38Z`. Original host network, environment values,
`unless-stopped`, target identities and the exact persistent mount were preserved. The previous
container is retained as `castfabric-rollback-20260906-94e993e-pre-alpha4`; mode-0600 inspection
records and metadata hashes stay on the Home Server under the matching dated rollback directory.
No production database/audio copy or backup was created on the workstation.

- Startup log confirmed 20 missing durations were filled. Three complete table-content hashes
  (media assets excluding duration, playlists and playlist items) matched before/after, including
  names, credits, tags, ordering, timestamps, IDs and revisions.
- TLS domain returned 0.11.0a4, 32 MCP tools/read-only list call, 20 available managed files,
  the same 16-section audiobook and four-track music playlist. Their totals are 16696.4506 and
  1141.1513 seconds respectively. All 20 Range requests returned 206 and exactly 128 requested bytes.
- Domain HTML/JS/CSS and both SVG SHA-256 digests exactly match the tested source files. Diagnostics
  contain no complete private LAN addresses or database/environment/audio attachments.
- Real domain browser checks passed Chinese desktop and English mobile utilities, source link,
  language switch, content and new-playlist dialog. Desktop dialog: x=420, width=600 at 1440×900.
  At 390×500: x=16, y=16, width=358, height=468; footer bottom=483, no horizontal overflow.
  Autofocus, inert background and Escape focus restoration passed; no browser page errors.

### Acceptance harness incident

The initial restart harness treated aggregate `health=healthy` as proof that all protocols had
finished starting. The API's existing suite contract reports healthy when a ready ingress exists;
the harness therefore asserted too early and automatically restored the old container. Runtime
logs show shutdown was requested during protocol initialization. This was not accepted as a pass.
The harness now waits for all three `ready=total=1` counters as well as healthy/zero sessions, with
the same bounded timeout. No runtime code, release tag or test threshold was changed. The same
immutable release image was promoted again; final restart results are recorded below.

Final production restart: `2026-09-06T14:24:25.129606880Z`. Docker healthy, all three protocols
`ready=total=1`, zero active/playing sessions, `PRAGMA integrity_check=ok`, no foreign-key violations,
and the pre-upgrade metadata hashes still match. Environment mappings, mount, host network and restart
policy match the previous container. Post-restart domain MCP, static hashes, 20 Range reads and
diagnostic privacy checks all passed again. The actual renderer reports stopped, volume 0, unchanged
from this turn's preflight; no sound or volume control command was sent. No audible-listening or
simultaneous-two-speaker result is claimed. Deployment and silent release acceptance are complete.
