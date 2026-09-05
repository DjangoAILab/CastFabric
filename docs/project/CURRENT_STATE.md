# CastFabric current state and session handoff

Last updated: 2026-09-05

This is the canonical starting point for a new development session. Read it together with
`AGENTS.md` before using older plans or prototypes: those files preserve design history and may
describe stages that are now complete.

## Product position

CastFabric is an open-source, self-hosted LAN audio fabric. It lets phones, computers and AI Agents
send audio to one or more physical speakers without making a vendor cloud account part of the core
path. The locked Chinese slogan is **“不挑协议，投了就播”**.

The implemented routing model is:

```text
DLNA / AirPlay / MiPlay inputs ─┐
                               ├─> one Receiver Suite per enabled output ─> standard DLNA DMR
MCP URL / file / PCM inputs ───┘
```

- Multiple speakers are first-class. Enabling or disabling one output never means selecting a
  single global speaker.
- Each enabled output owns an isolated Receiver Suite, protocol identities, ports, session state and
  activity records.
- Standard UPnP/DLNA output is the core adapter. Xiaomi MiNA/cloud support remains an optional legacy
  fallback, disabled by default; expired Xiaomi credentials must not break standard discovery or
  playback.
- The Python import package and some compatibility names remain `miair`. Product UI, docs, CLI and
  published artifacts use CastFabric. Do not start a broad package rename without a migration plan.

## Implemented user-facing capabilities

- Virtual DLNA, AirPlay/RAOP and MiPlay receivers for every enabled physical output.
- Generic SSDP discovery and persistent management of multiple standard DLNA renderers.
- Playback (including an optional whole-second start position), pause/stop, current-session seek
  where supported, volume and structured/redacted activity reporting.
- Chinese/English responsive console with Overview, Speakers, Playlists, Activity and AI Access
  surfaces plus secondary connection configuration. The Playlists area contains the user-facing
  content workbench, secondary audio-resource management and factual playback history.
- Embedded Streamable HTTP MCP at `/mcp` on the existing Web listener (`8300`); there is no MCP
  sidecar, extra container or extra listening port.
- Thirty-two MCP tools cover system/output discovery, persistent media assets, server playlists,
  progress/history, URL/file/real-time PCM playback and transport controls.
- A packaged Agent Skill under `skills/castfabric/` is now a thin local-data adapter: its helper
  uploads or plays a file, streams FFmpeg PCM, or performs a one-shot playlist import. Playlist
  execution and progress remain in CastFabric after the helper exits.
- Persistent content uses exactly six SQLite business tables under `/app/conf`; managed files use
  the same persistent mount. A failed playlist item records the reason and stops without retry,
  fallback or silent skipping, and restart never starts sound automatically.

The public product and deployment contract lives in `README.md` and `README.en.md`. The MCP/Skill
contract is recorded in `docs/plans/2026-09-01-castfabric-mcp-agent-skill-design.md` and
`docs/plans/2026-09-01-castfabric-agent-audio-implementation.md`.

## Architecture decisions that remain in force

1. Generic LAN discovery is independent of Xiaomi authentication (`docs/adr/0002-*`).
2. CastFabric uses a port/adapter core and the CastFabric product identity (`docs/adr/0003-*`).
3. Every output has an independent Receiver Suite (`docs/adr/0004-*`).
4. Console fields must come from the documented observability contract; do not guess a source App or
   claim an end-to-end latency that the service cannot measure (`docs/adr/0005-*`).
5. Runtime evolution goes through the suite registry (`docs/adr/0006-*`).
6. A playback command is not considered physically established until the target renderer pulls the
   media (`docs/adr/0007-*`).
7. Cached DLNA endpoints are refreshed after renderer port drift (`docs/adr/0008-*`).
8. AI support is a thin embedded MCP adapter over existing playback services (`docs/adr/0009-*`).
9. Positioned playback and current-session seek share one output primitive (`docs/adr/0010-*`).
10. Stable media assets and server-run playlists use the six-table SQLite model in ADR 0011, which
    supersedes the former no-stable-ID/no-server-playlist parts of ADR 0009 and ADR 0010
    (`docs/adr/0011-*`).

## Verification and deployment baseline

- Current released code commit: `3563c5bb549db67c4d4ad7b940db2e1babb660a7`.
- Current published prerelease: `v0.11.0-alpha.3`.
- Canonical repository: `https://github.com/DjangoAILab/CastFabric`.
- GHCR image: `ghcr.io/djangoailab/castfabric:v0.11.0-alpha.3`, published for
  `linux/amd64` and `linux/arm64`.
- Landing page: `https://djangoailab.github.io/CastFabric/`.
- GitHub Actions publish run `33647910803` passed Python/integration tests, Agent Skill tests,
  offline MiPlay validation, container cold-start/HTTP checks, multi-architecture publishing and
  prerelease creation.
- The Home Server runs feature-branch candidate `94e993e4ec8abf8200e577dfc3ffb97586529320`,
  image `sha-94e993e`, pinned to OCI index
  `sha256:9adaac8ead99c8e210a8e7644077db26795acc2d58275286b3b1cd888e781b74`.
  Feature CI `33944065999` and multi-architecture publish run `33944066270` passed.
  Domain-side silent acceptance covers TLS/static assets, bilingual desktop/mobile UI, 32-tool
  MCP discovery/call, six-table persistence across restart, privacy and unchanged target/readiness.
  Authorized physical-speaker checks passed two-item server-driven completion, actual media GETs,
  pause/resume/seek/navigation, active-resource conflict, uninterrupted reorder, persisted progress
  and explicit positioned resume. Final playback is stopped, volume is `33`, and active counts are
  zero. Nobody was home to listen: audible output is explicitly unverified, as accepted by the user.
  Earlier candidates were rolled back before local fixes for real DLNA timing/EOF and deleted-file
  re-upload; their incident evidence and the verified alpha.3 rollback point remain in the checklist.
- The repository was recreated after accidental remote deletion. Seven branches and nineteen tags
  were restored. The surviving GHCR package was reattached to the recreated repository with Actions
  `Write` access.
- Home Server and physical-speaker validation for DLNA, AirPlay, MiPlay, MCP file/PCM playback and
  OpenClaw is recorded—without credentials—in
  `docs/testing/castfabric-home-server-checklist.md`. That checklist is the source of truth for
  real-device status and rollback identifiers.

## Known boundary, not an open regression

On the currently tested speaker, direct DLNA playback usually responds in under one second, while
AirPlay and MiPlay live bridges are heard roughly four seconds later. Instrumentation already showed
MiPlay decode first-frame time around 3–4 ms and the physical DMR beginning its HTTP pull and receiving
PCM around 0.1 seconds. The remaining wait is most consistent with the renderer firmware prebuffering
live HTTP audio. Buffer/frequency experiments did not materially change it, and AirPlay showed the
same delay.

Do not restart speculative buffer tuning without new evidence. A meaningful next experiment needs a
different physical renderer or a native/low-latency output adapter that bypasses the current DLNA DMR
live-stream boundary. See `docs/architecture/live-bridge-latency.md`.

## Remaining work and explicit non-goals

- The server-playlist implementation and authorized single-speaker chain acceptance are complete.
  Audible listening and simultaneous progress on two physical speakers remain unverified; only one
  physical speaker was authorized. Do not infer those results from fake DMR or API checks.
- Still open in the real-device checklist: repeat standard-protocol checks while expired Xiaomi
  credentials are present, proving again that the core remains independent.
- Future output adapters are extension work, not implemented capability. The current core output is
  standard DLNA; do not advertise an unimplemented native speaker protocol.
- The archived Android AudioPlaybackCapture sender is not part of the current release. Its branch is
  retained for reference only.
- MCP is intended for a trusted LAN and has no public-Internet authentication. Do not expose `/mcp`
  directly to the Internet.
- Preserve the privacy contract: diagnostics and events must not expose credentials, URL query
  secrets or complete client/server addresses.

## Product and UI workflow

The accepted product model and production console are implemented. For any new UI/product change,
follow both the repository's mandatory workflow in `AGENTS.md` and the machine-level frontend design
instructions. Study relevant high-quality products, persist evidence, define information architecture
and data availability before styling, present materially different directions, then verify desktop,
mobile, Chinese, English, loading, empty, degraded and error states. Prototypes stay disconnected from
production APIs until explicitly accepted.

Do not regress these locked facts:

- Product name: CastFabric, not MiAir or MiPlay.
- Chinese slogan: “不挑协议，投了就播”.
- Multiple outputs are simultaneous managed entities, not a global single-selection control.
- Overview communicates capability and current system state; speaker management, activity and
  connection configuration keep separate information responsibilities.
- Only display data that the runtime contract can actually produce.

## Repository/worktree layout

The primary worktree belongs at the organization-aware GitHub path:

```text
/Users/wang/Project/github/DjangoAILab/CastFabric
```

An archived experimental linked worktree remains at:

```text
/Users/wang/MiAir-android-pcm   feat/android-pcm-cast
```

The linked worktree shares Git metadata with the primary repository. If the primary directory is
moved again, repair and verify the linked worktree's absolute `.git` pointer as part of the move.

The 2026-09-02 positioned-playback release was verified from the new path with 186 Python tests, all four
Agent Skill tests, and the offline MiPlay end-to-end self-test passing. The local Python 3.12 virtual
environment was recreated after the move so its launchers no longer reference the retired path.

## New-session checklist

1. Read `AGENTS.md` and this file.
2. Run `git status --short --branch`, `git worktree list`, `git remote -v`, and inspect recent commits.
3. Use `origin` (`DjangoAILab/CastFabric`) for project work. `upstream` is the historical MiAir source,
   not the publication target.
4. Read the relevant ADR/data contract before changing runtime, API, UI or protocol behavior.
5. For deployment/protocol work, read and update the Home Server checklist; distinguish automated,
   simulator and physical-device evidence.
6. Keep changes focused, test proportionally, update this handoff when product state, release baseline,
   deployment state or known limitations materially change.
