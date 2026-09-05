# CastFabric Home Server verification

Latest verification: 2026-09-05

Published baseline: `v0.11.0-alpha.3`

Network: `192.168.133.0/24`

Deployment baseline: restored `v0.11.0-alpha.3`; playlist progress/EOF fix awaiting redeployment.

Validated candidate image: `castfabric:proxy-origin-fix` (`linux/amd64`)

Pre-fix rollback container: `castfabric-rollback-0.11.0a1-pre-proxy-origin`

Pre-seek rollback container: `castfabric-rollback-0.11.0a2-pre-seek`

Server-playlists rollback container: `castfabric-rollback-20260905-3563c5b-pre-playlists`

## Server playlists candidate (2026-09-05)

- Branch: `codex/server-playlists`; deployed implementation commit:
  `0e68e9f668053dbd2b5e0e6edb5ae853e3595d09`.
- Feature CI run `33933686147` passed Python/integration, Agent Skill, offline MiPlay and Docker
  jobs. Publish run `33933891530` passed the same gates and published `linux/amd64` and
  `linux/arm64` images.
- Candidate tag: `ghcr.io/djangoailab/castfabric:sha-0e68e9f`; OCI index digest:
  `sha256:d6e1dc34d98137cb413ac42cfa3f2ee558f095679319d7268632a8857a92ff66`;
  deployed AMD64 manifest:
  `sha256:e8a475a48e66146aad0a6fc62fa88e65f67efff8ec37de180bcee163f2cdc5fc`.
- GHCR pulls from the Home Server returned EOF, so the already-published AMD64 manifest was pulled
  and revision-verified locally, then imported through the existing SSH channel. The deployed image
  label still resolves exactly to the candidate commit.
- Deployment completed at `2026-09-05T01:03:00Z` (`09:03` Asia/Shanghai). Host networking,
  `unless-stopped`, the existing `/app/conf` bind mount, target identity and enabled state were
  preserved.
- The pre-deployment `v0.11.0-alpha.3` image was tagged
  `castfabric:rollback-20260905-3563c5b-pre-playlists`; its stopped container uses the same rollback
  name. Full container and image inspection snapshots are stored mode `0600` in the deployment
  directory's dated `rollback/20260905-3563c5b-pre-playlists/` folder.

### Silent acceptance

- [x] Preflight found the production container healthy, one enabled/online target, one ready suite,
  DLNA/AirPlay/MiPlay each `1/1`, zero active/playing sessions, stopped playback and volume `33`.
- [x] An isolated bridge-network candidate exposed only a loopback Web port. Receiver protocols and
  Xiaomi extension were disabled; no production protocol port or registration was used.
- [x] Isolated cold start created exactly the six approved business tables. Asset/playlist CRUD,
  raw WAV upload, URL redaction, MCP initialize/list/call and restart persistence passed.
- [x] Production TLS page and static resources load. Browser checks passed Chinese and English,
  desktop and mobile layouts, the empty content workbench and the playback-history no-resume copy.
- [x] Production MCP initializes and exposes 32 tools. Every new media/playlist/progress/history tool
  and input schema is discoverable, and a read-only playlist call succeeds.
- [x] A temporary managed WAV, redacted external URL and playlist survived a formal-container
  restart from persistent `/app/conf`; the temporary playlist was then unlinked/archived and both
  visible test assets were deleted.
- [x] Diagnostic export omitted the test URL secret, an active upload ticket and complete LAN
  addresses. SQLite and the managed-media directory are on the existing persistent mount.
- [x] After cleanup and restart, the service is healthy, the original target remains online, all
  three receiver protocols remain `1/1`, playback is stopped, volume remains `33`, and active
  session/run counts are zero.
- [x] This silent gate issued no play, seek, pause, stop or set-volume commands. The user subsequently
  authorized real-speaker tests, accepting chain evidence because nobody is home to listen.

### Authorized device failure and rollback

- The initial two-item test did not advance. The real adapter omitted `GetPositionInfo`, while the
  integration fixture substituted synthetic status instead of exercising that SOAP path.
- A separate short physical DMR probe confirmed a GET for a 384,044-byte, nonzero 12-second WAV;
  reported position increased to 12 seconds, but transport remained PLAYING at EOF.
- The candidate was stopped and retained as `castfabric-failed-playlists-0e68e9f-20260905`; the
  verified alpha.3 rollback container was restored as `castfabric` at approximately `03:52Z`.
  Domain health, original target and all three protocol readiness counters returned to `1/1`.
- Test assets were removed after unlinking their archived test playlist. Device playback was
  stopped, volume remained `33`, and no active session/run remained before rollback.
- Local regression coverage now traverses actual SOAP status/position in the fake DMR, including
  both STOPPED-at-EOF and PLAYING-at-EOF. Completion while PLAYING requires exact reported duration,
  never elapsed wall time; optional timing/actions remain unknown when unsupported.
- Full candidate redeployment and transport/conflict acceptance remain pending. Audible listening
  and independent progress on two physical speakers are unverified (one authorized speaker).

### Re-upload boundary found during the next acceptance attempt

- Candidate `3bf15940f56403e8de3066eb6e00b72817499335` passed 224 local tests, feature CI
  `33943547373`, publish run `33943547936`, isolated checks and domain-side silent/restart checks.
- Re-uploading the exact previously deleted device-test WAV exposed a unique-hash collision with
  its retained tombstone. No playlist started in this attempt. The candidate was retained stopped
  as `castfabric-failed-playlists-3bf1594-20260905` and alpha.3 was restored again.
- The fix releases only a deleted row's blob-hash reservation in the same transaction that creates
  the new asset. The old asset ID and historical references remain deleted, while live-content
  deduplication remains intact. No schema/table addition, historical revival or data deletion is
  required; legacy tombstones are covered by the regression test.

Rollback preserves the failed candidate for inspection: stop and rename the current `castfabric`
container, rename `castfabric-rollback-20260905-3563c5b-pre-playlists` back to `castfabric`, then
start it. Only one host-network service may run at a time; verify domain health and all three suite
readiness counters after restoration.

## MiPlay field incident (2026-09-02)

- A real Android MiPlay session connected and forwarded volume successfully but produced no audible
  playback while the Home Server retained the earlier experimental output combination
  `l16 + range + play_type=0`.
- Runtime evidence isolated the failure downstream of the phone: CastFabric received MPEG-TS,
  FFmpeg emitted non-silent PCM, and the physical renderer performed an initial HTTP pull. The
  renderer then repeatedly requested a range near the end of the synthetic 2 GiB L16 resource and
  disconnected instead of consuming the live stream.
- Restored the supported/default physical-renderer combination
  `wav + close + audio/wav + play_type=2` and restarted the published
  `v0.11.0-alpha.2` container. The service returned healthy with DLNA, AirPlay and MiPlay all `1/1`
  ready.
- [x] Post-fix MiPlay simulation made the physical renderer pull `stream.wav`, decoded non-silent
  PCM in 4 ms, forwarded the first PCM in 123 ms, and completed with `output_started`,
  `pcm_forwarded`, `output_stopped` and no failure event.
- [ ] Repeat audible playback from the user's Android sender after the configuration repair.

## Agent audio gates

- [x] Streamable HTTP MCP initializes at `/mcp` on the existing `8300` listener; no second port,
  process, or container is required.
- [x] MCP exposes all 11 approved management, playback, and control tools on the published baseline.
- [x] `list_outputs` returns the configured and online physical renderer without Xiaomi credentials.
- [x] The packaged Agent Skill uploads a local WAV through the one-time file transaction and returns
  a playing MCP session.
- [x] The physical DMR performs the media HTTP GET; exactly one `agent.output_started` event records
  that verified pull.
- [x] The packaged Agent Skill converts and streams real-time `s16le / 48 kHz / stereo` PCM over the
  returned WebSocket.
- [x] Real PCM records `agent.output_started`, `agent.pcm_forwarded`, then
  `agent.output_stopped`, without `agent.output_failed`.
- [x] MCP volume and stop commands reach the physical renderer; the test restores the original
  volume (`14`).
- [x] After file and PCM tests, playback is stopped, active/playing session counts are zero, and
  DLNA, AirPlay, and MiPlay receiver health remains `1/1`.

## OpenClaw MCP regression

- [x] OpenClaw `2026.6.33` loads CastFabric as a native Streamable HTTP MCP server through
  `https://mi-air.internal.wj2015.com/mcp` with TLS verification enabled.
- [x] MCP discovery exposes all 11 baseline tools plus the declared resources and prompts.

## Positioned playback candidate (silent validation only)

- [x] URL and one-time file playback accept `start_position_seconds` in application, HTTP, MCP and
  Skill contracts without creating a media library or reusable asset ID.
- [x] Current playback exposes absolute-second seek with optional `if_session_id` concurrency guard.
- [x] Fake DMR and adapter tests confirm both flows reuse DLNA AVTransport `Seek` with `REL_TIME`.
- [x] Failure tests confirm an output started for positioned playback is stopped if its initial Seek
  is rejected, and the application session is marked failed.
- [x] After publishing and deployment, OpenClaw discovers all 12 tools. This gate was discovery
  only: do not call play, seek, pause, stop, or volume on the physical renderer during this release.
- [x] `v0.11.0-alpha.3` is healthy on the Home Server with DLNA, AirPlay and MiPlay all `1/1` ready,
  and zero active or playing sessions after deployment.
- [x] The released Skill is installed at OpenClaw's workspace Skill path, is visible to the model,
  and passes `openclaw skills info/check` on OpenClaw `2026.6.33`.
- [x] Management and read-only playback coverage passes: system status, output listing, output scan,
  playback status, and a no-op output update.
- [x] URL playback and transport controls pass, and the test restores playback to stopped.
- [x] File playback returns an HTTPS one-time upload URL; the upload succeeds without redirects and
  the physical renderer performs the direct LAN media pull.
- [x] PCM playback returns a WSS stream URL; an unmodified client sends 20 frames / 192,000 bytes and
  closes normally with WebSocket code `1000`.
- [x] Physical-output events confirm `agent.output_started`, `agent.pcm_forwarded`, and
  `agent.output_stopped` with no `agent.output_failed`.
- [x] Final volume is restored to `14` and playback is stopped.

The proxy regression deliberately separates the two address planes: Agent-facing transaction URLs
retain the ingress HTTPS/WSS origin, while renderer-facing media URLs use direct LAN HTTP. This keeps
the MCP client on the internal domain without asking the DLNA speaker to resolve that domain or
follow the reverse proxy.

## Automated gates

- [x] Container reaches Docker `healthy` state.
- [x] Web status reports CastFabric `0.10.0a1`.
- [x] Xiaomi extension is disabled and startup performs no Xiaomi login or token refresh.
- [x] Local DLNA control is available without Xiaomi authentication.
- [x] Generic SSDP discovery finds the physical renderer at `192.168.133.132`.
- [x] SSDP advertises the virtual renderer from the Home Server at `192.168.133.5`.
- [x] MiPlay discovery finds `CastFabric · 卧室小爱 hd` on control port `8899`.
- [x] AirPlay/RAOP registration is present in startup diagnostics.
- [x] Existing virtual-renderer UDN remains unchanged across migration.
- [x] Previous working container is retained as a stopped rollback image.
- [x] `/api/v1/system` reports one healthy Receiver Suite with DLNA, AirPlay and MiPlay all `1/1` ready.
- [x] Production console, safe settings API and redacted diagnostic ZIP load from the installed wheel.
- [x] Diagnostic export contains no credentials, URL query secrets, or complete Home Server/speaker IPs.

## Candidate protocol gates

- [x] Standard target scan finds the physical DMR at `192.168.133.132` without Xiaomi authentication.
- [x] Independent SSDP scan sees both the physical DMR and the CastFabric virtual renderer.
- [x] MiPlay mDNS scan finds `CastFabric · 卧室小爱 hd` at `192.168.133.5:8899`.
- [x] RAOP browse finds the per-target CastFabric AirPlay service and its independent TCP port.
- [x] Production MiPlay simulation reaches the physical speaker: DMR HTTP GET is confirmed, then PCM is
  forwarded; the structured event sequence ends successfully with no `output_failed`.
- [x] Virtual DLNA receives real `SetAVTransportURI`/`Play` SOAP and the physical DMR GETs a 61,780-byte
  local WAV payload.
- [x] System returns to `healthy`, zero active sessions, and one ready suite after both streaming POCs.
- [x] Renderer-port drift incident reproduced: cached endpoint `:1269` rejects connections while the
  same UDN advertises `:2026` after reboot.
- [x] Recovery candidate rediscovers `:2026` from a deliberately stale client and completes a real
  `GetVolume` SOAP request without restarting CastFabric.
- [x] Recovery candidate virtual DLNA path makes the physical DMR pull a 192,044-byte WAV payload.
- [x] Recovery candidate MiPlay path records `output_started` and `pcm_forwarded` without
  `output_failed`.

## Real-device gates

These checks require a phone or Apple sender and are intentionally kept separate from automated
candidate acceptance. They remain the post-release alpha field checklist rather than being inferred
from the simulator or mDNS browse.

- [x] Android MiPlay: discover, connect, play, pause, seek and volume.
- [x] iOS/macOS AirPlay: discover, connect, play, pause and volume.
- [x] DLNA direct to the physical renderer: play, pause and volume.
- [x] DLNA to the CastFabric virtual renderer: play, pause and volume.
- [ ] Repeat the standard-protocol checks with expired Xiaomi credentials present.

## Rollback

The pre-fix published service is retained as
`castfabric-rollback-0.11.0a1-pre-proxy-origin`. Restore only one service at a time because the
ingress protocols bind host-network ports.
