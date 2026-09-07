# Multi-protocol boundary hardening and alpha.5 verification

User authorization: commit, push, release, deploy and accept on 2026-09-07.

## Release

- Release commit: `9d400f711b82c8a0a463c6a6e09e9c1b1d932a36`.
- Annotated tag: `v0.11.0-alpha.5`; tag object `02d124000beed63b493cad328443dfcf3f543be0`.
- Main workflow `34081095632` and tag workflow `34081736315` both passed. The tag workflow created
  the GitHub prerelease at `2026-09-07T04:06:08Z`.
- OCI index: `sha256:010654cd4ec99926115b316e96f5028a506bf8f7f8913a6f8a11bd3271961ff6`.
- AMD64 manifest: `sha256:e3e9491e0e668d144413c4ac0ead489508965a26ea1452c10a7923a9bb8b396d`.
- ARM64 manifest: `sha256:4672b5d0fec05f901a029f51ac3a030ff01f0099e3b63134cd0b7f3b81a63adb`.
- Home Server image ID: `sha256:265fd8eb34c63bd8ea218cc56ec96ba35b8514567ef362fcd2fb3a1e4d526f0b`.

Local gates passed with Python 3.12.12: 245 Python tests, five Agent Skill tests, the direct audio
Seek script, the offline MiPlay self-test, version synchronization, Docker build, and local image
cold-start HTTP/MCP checks. The offline self-test produced non-silent 48 kHz stereo PCM.

## Deployment

The exact published image first passed an isolated bridge-network cold start on the Home Server.
The disposable container and named volume were removed. Production replacement preserved the host
network, `unless-stopped`, the exact persistent `/app/conf` bind mount and CastFabric environment
values. No schema migration or workstation backup was required. The old alpha.4 container remains
stopped as `castfabric-rollback-20260907-d6e7a07-pre-alpha5`.

Preflight found one online output and all protocols ready. The physical renderer was paused at
second 13 of 695, volume 28, with an old persisted MCP playlist session. Alpha.5 startup marked that
session `interrupted`, preserving its saved position. The renderer remained paused and did not start
sound automatically; the later controlled chain test ended it in stopped state.

Final restart: `2026-09-07T04:19:57.408167782Z`. Docker is healthy, DLNA/AirPlay/MiPlay are ready,
the suite has no owner, there are zero active sessions and playlist runs, and the renderer is stopped
at volume 28.

## Boundary and media acceptance

- A raw idle connection to port 8899 raised only `control_connections=1`; `active_session` remained
  false and the media-session set did not change. At the 15-second deadline the server count returned
  to zero. The client drained the 24-byte buffered challenge and then observed EOF.
- The MiPlay receiver self-scan returned one audio-capable receiver on port 8899. Its stable
  target-derived device identity matched before and after the final restart.
- A 0.35-second simulated MiPlay source completed control authentication and RTSP, sent six media
  frames / 7,708 media bytes, and produced non-silent PCM with peak 2,969. FFmpeg emitted first PCM
  in 14 ms. The physical DMR pulled the WAV stream and the event journal contains `session.started`,
  `miplay.output_started`, `miplay.pcm_forwarded` and `miplay.output_stopped`, with no MiPlay failure.
- Domain TLS reports `0.11.0a5`; MCP initializes with 32 tools and its read-only system call passes.
  All 20 managed files returned HTTP 206 with the requested 128-byte ranges. Both curated playlist
  IDs and revisions remain unchanged.
- SQLite has exactly the six approved business tables, `integrity_check=ok`, no foreign-key
  violations and zero active session/run rows. The diagnostic archive contains no Xiaomi credential
  fields or complete Home Server/speaker addresses. Post-restart logs contain no traceback,
  `EventLoopBlocked` or error entry.

The controlled chain proves network media, decode, non-silent PCM and physical renderer pull. Nobody
reported hearing the tone, so audible output is intentionally not claimed. A real Xiaomi phone still
needs to confirm visibility in its current MIUI cast picker and complete a real Open. With only one
configured output, simultaneous playback on two physical speakers also remains unverified.

## Harness corrections

Three acceptance assertions were corrected without changing runtime code, release artifacts or test
thresholds:

1. Ended sessions are not returned by the runtime session endpoint; the pre-deployment session's
   `interrupted` state was therefore verified directly in SQLite.
2. The official MCP SDK exposes `CallToolResult.is_error`, not `isError`.
3. An idle client can read the already-buffered 24-byte MiPlay challenge after the server closes;
   closure was verified from the server connection count and by draining through EOF. The event
   contract uses `session.started`, not a nonexistent `miplay.media_started` event.
