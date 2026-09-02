# CastFabric Home Server verification

Latest verification: 2026-09-02

Published baseline: `v0.11.0-alpha.2`

Network: `192.168.133.0/24`

Deployment baseline: `v0.11.0-alpha.2`

Validated candidate image: `castfabric:proxy-origin-fix` (`linux/amd64`)

Pre-fix rollback container: `castfabric-rollback-0.11.0a1-pre-proxy-origin`

## Agent audio gates

- [x] Streamable HTTP MCP initializes at `/mcp` on the existing `8300` listener; no second port,
  process, or container is required.
- [x] MCP exposes all 11 approved management, playback, and control tools.
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
- [x] MCP discovery exposes all 11 tools plus the declared resources and prompts.
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
