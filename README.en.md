<p align="center"><img src="docs/assets/castfabric-mark.svg" width="104" alt="CastFabric mark"></p>
<h1 align="center">CastFabric</h1>
<p align="center"><strong>Cast it. It plays.</strong></p>
<p align="center">One local-audio fabric for phones, computers, and AI agents: DLNA, AirPlay, MiPlay, and MCP.</p>

<p align="center">
  <a href="https://github.com/DjangoAILab/CastFabric/actions/workflows/test.yml"><img alt="Test status" src="https://github.com/DjangoAILab/CastFabric/actions/workflows/test.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/DjangoAILab/CastFabric/releases"><img alt="GitHub release" src="https://img.shields.io/github/v/release/DjangoAILab/CastFabric?include_prereleases&sort=semver"></a>
  <a href="https://github.com/DjangoAILab/CastFabric/pkgs/container/castfabric"><img alt="GHCR image" src="https://img.shields.io/badge/GHCR-amd64%20%7C%20arm64-1f2523"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-cb7a18"></a>
</p>
<p align="center"><a href="README.md">简体中文</a> · English</p>

![CastFabric console overview](docs/assets/console-overview.png)

CastFabric routes audio from phones, computers, and AI agents to speakers on your LAN. Phones keep
using DLNA, AirPlay, or MiPlay; agents use the embedded MCP endpoint for URLs, local files, and live
PCM. The core output targets standard UPnP/DLNA MediaRenderers and does not depend on a Xiaomi
account. Xiaomi cloud remains an explicitly enabled legacy compatibility extension.

Every enabled output gets its own `CastFabric · <speaker name>` receiver suite. Different speakers
can play concurrently, while protocols targeting the same speaker share an isolated session owner.
There is no global “default speaker” in the product model.

## Why CastFabric

- **Multiple inputs, one output model:** virtual DLNA, AirPlay and MiPlay all terminate at a standard
  DLNA output adapter.
- **Multiple speakers, independently managed:** every output owns its receiver suite, sessions,
  ports and activity history.
- **No vendor-account dependency:** DLNA discovery and playback survive expired Xiaomi tokens and
  public-internet outages.
- **AI can address real speakers directly:** `/mcp` exposes discovery, management, playback, and
  control from the existing service—without a sidecar, second container, or additional port.
- **Native DLNA stays visible:** choose the physical renderer directly when minimum latency matters.
- **Success is verified:** CastFabric confirms that the physical renderer pulls the HTTP audio stream;
  a successful SOAP `Play` response alone is not reported as audible output.
- **No invented product data:** the console does not guess source apps or label decoder timing as
  end-to-end audible latency.
- **Privacy by default:** diagnostics remove URL queries, credentials and complete IPv4/IPv6 addresses.

## Audio path

```text
Phone / computer ── DLNA / AirPlay / MiPlay ──┐
                                               ├─▶ Receiver Suite (one per speaker) ─▶ DLNA output ─▶ Speaker
AI agent ── MCP: URL / file / live PCM ───────┘

Speaker A: DLNA + AirPlay + MiPlay + MCP ─▶ Output A
Speaker B: DLNA + AirPlay + MiPlay + MCP ─▶ Output B
```

The current MiPlay path is AAC → 48 kHz stereo PCM → HTTP WAV/L16 → physical DLNA DMR. The receiver
was independently implemented from public material and observed wire behavior. It ships as a
prerelease capability in the `0.10` line.

## AI and MCP

CastFabric `0.11` serves Streamable HTTP MCP from the existing Web listener. If the console is at
`http://192.168.1.10:8300`, the MCP endpoint is `http://192.168.1.10:8300/mcp`. It reuses the same
`target_id`, playback state, and output adapters rather than introducing a second playback service.

Twelve atomic tools are available:

- management: system status, list and scan speakers, enable/disable or rename an output;
- playback: HTTP(S) URL, agent-local file, and live `s16le / 48 kHz / stereo` PCM;
- control: status, pause, stop, absolute-second seek, and volume.

The bundled [CastFabric Agent Skill](skills/castfabric/SKILL.md) adds local-file upload, FFmpeg live
conversion, positioned URL/file playback, current-session seek, and client-side sequential or
looping playlists. A session ID is only an optional concurrency guard, never a reusable media ID.
MCP stays thin: CastFabric **does not embed TTS, a media library, or a server-side queue**. The agent
creates or selects audio; CastFabric delivers it to the chosen speaker.

> MCP currently targets trusted LANs and has no public-internet authentication. Do not expose
> `/mcp` directly to the internet.

### Latency boundary

- **Native DLNA casting:** normally starts in under one second on the current test speaker and is the
  preferred route when responsiveness matters.
- **AirPlay / MiPlay live bridging:** has about four seconds of observed audible delay on the current
  test speaker. MiPlay emits its first decoded PCM in about 3–4 ms, and the speaker starts pulling and
  receiving PCM in about 0.1 s. The remaining delay is most consistent with firmware read-ahead for
  a live HTTP stream, which standard DLNA controls cannot disable.

Four seconds is not a universal constant for every renderer, but lip sync is not promised until a
native or low-latency output adapter exists. Choose the physical renderer's DLNA entry when minimum
latency matters. See [Live-bridge latency boundary](docs/architecture/live-bridge-latency.md) for the
evidence, eliminated variants and future POCs.

## Quick start with Docker

SSDP and mDNS need LAN multicast. A Linux home server with host networking is recommended:

```bash
git clone https://github.com/DjangoAILab/CastFabric.git
cd CastFabric
docker compose pull
docker compose up -d
```

Open `http://HOST_IP:8300`, then use **Connection settings** to scan and enable output speakers.
Standard DLNA speakers do not require a Xiaomi login. Configuration is persisted in `./conf`.

```dotenv
CASTFABRIC_HOSTNAME=192.168.1.10
CASTFABRIC_CONFIG_DIR=./conf
```

| Purpose | Default port |
|---|---:|
| Web console | `8300/tcp` |
| Virtual DLNA and media service | `8200/tcp` |
| MiPlay control base | `8899/tcp` |
| SSDP / mDNS | `1900/udp`, `5353/udp` on the host network |

The repository also includes non-destructive management scripts:

```bash
./deploy.sh local       # Build current source
./deploy.sh pull        # Pull the published image
./manage.sh status
./manage.sh logs -f
```

## Console

- **Overview:** current routes, verifiable sender information, protocol and destination. It keeps the
  desktop view within one screen and summarizes additional routes.
- **Speakers:** manage multiple outputs, receiver aliases, suite enablement and protocol health.
- **Activity:** inspect structured sessions and typed failures with server-side redaction.
- **AI Access:** copy the current MCP endpoint, client configuration, and verification prompt without
  managing another service port.

Connection, playback, ports and optional extensions live in a secondary **Connection settings** panel.
The complete console switches between Chinese and English.

<p align="center"><img src="docs/assets/console-mobile.png" width="360" alt="CastFabric mobile console"></p>

## Local development and verification

Python 3.10+ and FFmpeg are required:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
castfabric --conf-path conf
```

```bash
python -m pytest -q
castfabric-miplay self-test --duration 0.35
castfabric-miplay scan --timeout 5
castfabric-miplay simulate --target 192.168.1.20 --duration 1
```

Release gates cover unit and integration tests, Agent Skill tests, MCP cold start, real-speaker file
and PCM pulls, a two-DMR protocol POC, legacy migration and rollback reading, diagnostic privacy, and
amd64/arm64 GHCR builds.

## Migration, architecture and protocol notes

- [MiAir / OpenXiaoCast migration and rollback](docs/migration/miair-to-castfabric.md)
- [Runtime v2 architecture](docs/architecture/castfabric-runtime-v2-design.md)
- [One Receiver Suite per output](docs/adr/0004-one-receiver-suite-per-output.md)
- [Verified physical DMR pull boundary](docs/adr/0007-verify-physical-output-pull.md)
- [AirPlay / MiPlay live-bridge latency boundary](docs/architecture/live-bridge-latency.md)
- [Console data contract](docs/architecture/castfabric-console-data-contract.md)
- [MiPlay sources and independent implementation boundary](docs/research/miplay-protocol-sources.md)
- [Home Server acceptance checklist](docs/testing/castfabric-home-server-checklist.md)
- [MCP and Agent Skill design](docs/plans/2026-09-01-castfabric-mcp-agent-skill-design.md)

## Compatibility and open source

CastFabric is released under the [MIT License](LICENSE). During migration it retains the `miair`,
`openxiaocast` and `openxiaocast-miplay` commands, the `miair` Python package, existing configuration
volumes, and stable virtual-device UDNs.

The project builds on and credits [MiAir](https://github.com/KiriChen-Wind/MiAir),
[XiaoMusic](https://github.com/hanxi/xiaomusic),
[AirPlay2 Receiver](https://github.com/openairplay/airplay2-receiver), and
[Macast](https://github.com/xfangfang/Macast). The MiPlay implementation does not import third-party
source with unclear licensing.
