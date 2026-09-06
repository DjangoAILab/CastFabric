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

## Release / deployment status

Pending CI, published immutable image, isolated image gate and Home Server rollout. Home Server preflight
observed actual playback of a 1,234-second chapter at volume 25; deployment must not interrupt this without
confirmation. Update this section with actual run IDs and evidence, not intended outcomes.
