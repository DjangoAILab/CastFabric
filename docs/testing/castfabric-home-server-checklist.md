# CastFabric Home Server verification

Date: 2026-08-30

Network: `192.168.133.0/24`

Deployment commit: `e4237e2`

Candidate image: `castfabric:e4237e2` (`linux/amd64`)

Rollback container: `castfabric-rollback-54f104c`

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

## Real-device gates

These checks require a phone or Apple sender and are intentionally kept separate from automated
candidate acceptance. They remain the post-release alpha field checklist rather than being inferred
from the simulator or mDNS browse.

- [ ] Android MiPlay: discover, connect, play, pause, seek and volume.
- [ ] iOS/macOS AirPlay: discover, connect, play, pause and volume.
- [ ] DLNA direct to the physical renderer: play, pause and volume.
- [ ] DLNA to the CastFabric virtual renderer: play, pause and volume.
- [ ] Repeat the standard-protocol checks with expired Xiaomi credentials present.

## Rollback

The pre-deployment CastFabric container is retained as
`castfabric-rollback-54f104c`. Earlier CastFabric rollback containers and the MiAir container
`miair-rollback-30c7a79` remain stopped. Restore only one service at a time because all
three ingress protocols bind host-network ports.
