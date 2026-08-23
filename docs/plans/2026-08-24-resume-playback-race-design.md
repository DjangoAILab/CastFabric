# Resume Playback Race Design

## Problem

When an M01 speaker resumes after a long pause, MiAir can report `PLAYING` to the DLNA controller while the physical speaker remains silent. The observed sequence is: periodic cleanup removes media buffers, `play()` creates a replacement buffer, `create_seek_url()` sees `total_size == 0` before the HTTP headers arrive and returns `None`, and the renderer silently falls back to a non-seek proxy URL. The MiNA `play_by_url` acknowledgement only confirms command forwarding, not audible playback.

## Design

Keep the fix inside the existing renderer, device server, and media buffer boundaries. Buffer cleanup will calculate protected buffer IDs from renderer `current_uri`/`next_uri`, active proxy requests, and live source mappings, then use that protection consistently for TTL, count, and memory cleanup. Source buffers remain reusable while a renderer may resume them; derived seek buffers remain disposable.

`create_seek_url()` will wait for response headers before validating size and will wait for download completion before constructing seek media. Resume playback will request the seek URL before creating a normal proxy URL. If a non-zero resume cannot produce a seek URL, `play()` fails instead of falsely starting from the beginning.

The existing media-proxy completion event is the readiness gate: the endpoint already waits for the complete buffer before responding. Tests will cover a zero-sized buffer becoming ready, protected cleanup under count and memory pressure, and renderer behavior when resume seek creation fails. Deployment verification will include unit tests, container health, cold restart, sanitized log inspection, and a controlled cleanup/resume regression probe.

## Error handling and rollback

Header or download timeout returns a clear failure without publishing `PLAYING`. Buffer errors remain visible in logs. The previous image and stopped backup container are retained until verification passes, allowing immediate rollback without rebuilding.
