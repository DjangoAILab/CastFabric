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

All test gates passed; tag run `34032488040` attempt 2 and main run `34032487886` are still building
multi-architecture publication images. Published immutable image verification and Home Server rollout
remain pending. Home Server preflight observed actual playback of a 1,234-second chapter at volume 25,
then Sleep at volume 30; deployment must not interrupt this without confirmation. The live container
remains healthy and unchanged at the pinned `94e993e` candidate. Local final-source isolated image
acceptance is complete, but must not be confused with verification of the eventual published digest.
