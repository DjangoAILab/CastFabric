# CastFabric Home Server verification

Date: 2026-08-29  
Network: `192.168.133.0/24`  
Deployment commit: `28b5e29`  
Container image: `castfabric:28b5e29`

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

## Real-device gates

These checks require a phone or Apple sender and are intentionally kept separate
from deployment automation.

- [ ] Android MiPlay: discover, connect, play, pause, seek and volume.
- [ ] iOS/macOS AirPlay: discover, connect, play, pause and volume.
- [ ] DLNA direct to the physical renderer: play, pause and volume.
- [ ] DLNA to the CastFabric virtual renderer: play, pause and volume.
- [ ] Repeat the standard-protocol checks with expired Xiaomi credentials present.

## Rollback

The pre-deployment CastFabric container is retained as
`castfabric-rollback-6371b20`. The earlier MiAir container is retained as
`miair-rollback-30c7a79`. Restore only one service at a time because all three
ingress protocols bind host-network ports.
