# CastFabric Agent Audio Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose CastFabric's existing output management, URL/file/PCM playback, and playback controls to AI agents through an embedded Streamable HTTP MCP endpoint and a reusable Agent Skill.

**Architecture:** Embed a stateless Streamable HTTP MCP endpoint at `/mcp` in the existing CastFabric aiohttp service. The console API, MCP control plane, one-time raw file uploads, and PCM WebSocket data plane share the existing process, container, and listening port. MCP tools call the same application services as the console rather than loopback HTTP. Ship a Node.js Skill helper for deterministic local-file upload, FFmpeg PCM production, and client-side playlist orchestration.

**Tech Stack:** Python 3.10+, aiohttp, existing CastFabric runtime/PlaybackTarget/CastFabricLiveAudioSink, official Python MCP SDK v2, Node.js 22 built-ins, FFmpeg, pytest, Node test runner.

---

## Locked implementation choice

Use an **embedded Streamable HTTP MCP endpoint**, not a local stdio sidecar and not another Home Server service.

Non-negotiable deployment constraint for the first release:

- Home Server remains one process, one container, and one listening port (the existing CastFabric
  web port, currently `9988` by default);
- REST requests, raw uploads, and WebSocket upgrades all share that port under `/api/v1`;
- Streamable HTTP is served at `/mcp` by the existing CastFabric listener;
- Docker Compose, firewall rules, reverse proxy configuration, and health checks gain no new port.

```text
Codex / Claude Code / other MCP clients
        │ Streamable HTTP JSON-RPC /mcp
        │ one-time file upload + WebSocket PCM, all through :9988
        ▼
CastFabric aiohttp process on Home Server
        │ MCP tools call PlaybackService directly
        │ existing PlaybackTarget / LiveAudioSink
        ▼
physical output target
```

Why this is the selected implementation:

- CastFabric is already a long-running self-hosted HTTP service, so MCP belongs to the same product
  and deployment boundary;
- Codex, Claude Code, and other clients can connect directly to one stable LAN URL;
- the Home Server gains one route on its existing listener, not another service, port, or process;
- file and PCM bytes avoid JSON/Base64 overhead by using one-time data-plane URLs on that same port;
- the official SDK's ASGI MCP application is attached through a narrow, tested aiohttp adapter;
  the MCP protocol itself is not reimplemented.

Rejected:

1. **Local stdio sidecar:** can read Agent-local files, but adds client installation/lifecycle work
   and duplicates a server boundary already owned by CastFabric.
2. **Independent MCP service on the Home Server:** adds another deployed service/port and still
   needs a separate upload path for client-local files.
3. **Base64 audio in MCP JSON-RPC:** simple for tiny fixtures but inefficient and memory-heavy for
   real media; it is not a public playback contract.

## Public contracts

### OutputTarget

The existing normalized `target_id` remains the only output identifier.

```json
{
  "target_id": "uuid:...",
  "kind": "dlna",
  "name": "客厅音箱",
  "receiver_alias": "CastFabric · 客厅音箱",
  "configured": true,
  "enabled": true,
  "online": true,
  "observed_at": "2026-09-01T12:00:00Z",
  "capabilities": ["AVTransport", "RenderingControl"],
  "suite_health": "healthy"
}
```

### Home Server playback endpoints

```text
POST /api/v1/playback/url
POST /api/v1/playback/files                create one-time upload
PUT  /api/v1/playback/files/{upload_id}    raw bounded file body
POST /api/v1/playback/streams
GET  /api/v1/playback/streams/{stream_id}  WebSocket upgrade
GET  /api/v1/playback/{target_id}
POST /api/v1/playback/{target_id}/pause
POST /api/v1/playback/{target_id}/stop
POST /api/v1/playback/{target_id}/volume
```

All JSON success responses use:

```json
{"ok": true, "target_id": "uuid:...", "state": "playing"}
```

All business failures reuse the current API envelope:

```json
{"error": {"code": "TARGET_NOT_FOUND", "message_key": "error.target_not_found", "details": {}}}
```

### MCP tools

```text
get_system_status
list_outputs
scan_outputs
update_output
play_url
play_file
open_pcm_stream
get_playback_status
pause
stop
set_volume
```

`play_file` starts a one-time upload transaction from `target_id`, display filename, content type,
and size, then returns an opaque upload URL on the same CastFabric origin. Playback starts only
after the Skill/helper uploads the bytes. `open_pcm_stream` only creates the fixed-format PCM input
and returns its WebSocket address; the Skill helper owns producing and writing PCM bytes.

## Execution setup

After plan approval:

1. Push the two accepted design commits on `main`.
2. Create branch `feat/agent-audio-mcp` in the primary
   `/Users/wang/Project/github/DjangoAILab/CastFabric` worktree.
3. Do not alter or reuse `/Users/wang/MiAir-android-pcm`.
4. Use TDD and commit after every independently passing task below.

### Task 1: Align the persisted contract with embedded Streamable HTTP MCP

**Files:**
- Modify: `docs/adr/0009-expose-agent-audio-through-thin-mcp-adapter.md`
- Modify: `docs/plans/2026-09-01-castfabric-mcp-agent-skill-design.md`
- Commit: documentation only

**Step 1: Replace the Base64 MCP file input**

Document that MCP `play_file` creates a bounded one-time upload transaction and returns an opaque
same-origin upload URL. The Agent Skill validates the local path and uploads raw bytes. Base64 is
not the public tool contract.

**Step 2: Record the hosting split**

Document that `/mcp`, HTTP uploads, and WebSocket streams run inside the existing CastFabric process
and share its web port. MCP handlers call application services directly.

**Step 3: Check the documents**

Run:

```bash
git diff --check
rg -n "Base64|stdio|Streamable HTTP|multipart|WebSocket|/mcp" docs/adr/0009-* docs/plans/2026-09-01-castfabric-mcp-agent-skill-design.md
```

Expected: no whitespace errors; public file tool is described as a one-time upload transaction.

**Step 4: Commit**

```bash
git add docs/adr/0009-* docs/plans/2026-09-01-castfabric-mcp-agent-skill-design.md
git commit -m "design: embed MCP in CastFabric web service"
```

### Task 2: Make configured output identity explicit

**Files:**
- Modify: `miair/runtime/models.py`
- Modify: `miair/web/api_v1.py`
- Modify: `tests/test_api_v1.py`
- Modify: `tests/test_runtime_models.py`

**Step 1: Write failing API tests**

Add assertions that:

- a persisted target returns `configured: true`;
- a discovered-only target returns `configured: false` and `enabled: false`;
- `id` remains for console compatibility while the MCP client maps it to `target_id`;
- `online` remains `null` before a completed scan.

**Step 2: Run the focused tests**

```bash
pytest tests/test_api_v1.py tests/test_runtime_models.py -q
```

Expected: new assertions fail because `configured` is absent.

**Step 3: Add the field without changing target lifecycle**

Set `configured = target is not None` in `_target_item()`. Add `configured` to
`OutputTargetSnapshot` only where typed snapshots expose the same object; do not rename persisted
configuration or current console fields.

**Step 4: Re-run tests and commit**

```bash
pytest tests/test_api_v1.py tests/test_runtime_models.py -q
git add miair/runtime/models.py miair/web/api_v1.py tests/test_api_v1.py tests/test_runtime_models.py
git commit -m "feat: expose configured output state"
```

Expected: all focused tests pass.

### Task 3: Add one playback application service

**Files:**
- Create: `miair/playback/__init__.py`
- Create: `miair/playback/service.py`
- Create: `tests/test_playback_service.py`
- Modify: `miair/runtime/models.py`
- Modify: `miair/app.py`

**Step 1: Write fake-target tests**

Cover:

- normalized target lookup;
- unknown target and disabled target errors;
- `play_url`, `pause`, `stop`, `set_volume`, and `get_status` delegate exactly once to the existing
  controller;
- volume is normalized to `0..100` by the existing target contract;
- an MCP playback begins a session with protocol `mcp` and transitions to `playing` after the target
  accepts the command;
- a failed target command ends the session as failed;
- `stop` ends the current MCP-owned session but does not delete unrelated receiver suites.

**Step 2: Verify tests fail**

```bash
pytest tests/test_playback_service.py -q
```

Expected: import or enum failure because the service and `IngressProtocol.MCP` do not exist.

**Step 3: Implement the minimal service**

Create `PlaybackService` with these async methods:

```python
async def play_url(target_id: str, url: str, *, media_format: str | None = None) -> dict: ...
async def pause(target_id: str) -> dict: ...
async def stop(target_id: str) -> dict: ...
async def set_volume(target_id: str, volume: int) -> dict: ...
async def get_status(target_id: str) -> dict: ...
def controller_for(target_id: str): ...
```

Use `suite_registry.get(target_id).controller`; do not import a concrete DLNA or Xiaomi adapter.
Add `IngressProtocol.MCP = "mcp"`. Construct the service once on the application object.

**Step 4: Verify and commit**

```bash
pytest tests/test_playback_service.py tests/test_media_sessions.py tests/test_receiver_suites.py -q
git add miair/playback miair/runtime/models.py miair/app.py tests/test_playback_service.py
git commit -m "feat: add protocol-neutral playback commands"
```

Expected: focused and existing session/suite tests pass.

### Task 4: Expose URL and control commands through API v1

**Files:**
- Modify: `miair/web/api_v1.py`
- Modify: `tests/test_api_v1.py`
- Modify: `tests/test_runtime_redaction.py`

**Step 1: Write route contract tests**

Test exact JSON and status codes for:

- URL playback success;
- invalid/non-HTTP URL;
- target not found, disabled, or offline;
- get playback status;
- pause, stop, and volume;
- volume values that are not numeric;
- URLs in diagnostics/events remain redacted according to existing rules.

**Step 2: Run and observe 404 failures**

```bash
pytest tests/test_api_v1.py tests/test_runtime_redaction.py -q
```

Expected: new endpoints return 404.

**Step 3: Add the routes**

Validate only the fields named in the public contract. Resolve and call `app.playback_service`.
Reuse `_error()` and do not return controller exception strings or full URLs.

**Step 4: Verify and commit**

```bash
pytest tests/test_api_v1.py tests/test_runtime_redaction.py -q
git add miair/web/api_v1.py tests/test_api_v1.py tests/test_runtime_redaction.py
git commit -m "feat: expose playback control API"
```

### Task 5: Add one-time file-upload playback

**Files:**
- Create: `miair/playback/files.py`
- Create: `tests/test_playback_files.py`
- Modify: `miair/playback/service.py`
- Modify: `miair/web/api_v1.py`
- Modify: `miair/app.py`

**Step 1: Write lifecycle and HTTP tests**

Cover:

- transaction creation requires `target_id`, safe display filename, content type, and bounded size;
- upload accepts one raw body exactly once and rejects expired, replayed, or oversized writes;
- filename is reduced to a safe display name and never used as the served path;
- only an opaque random token appears in the speaker URL;
- directory listing and unknown tokens return 404;
- the physical fake target receives the generated HTTP URL;
- GET starts output verification and returns exact bytes/MIME type;
- HEAD and required byte ranges behave consistently enough for DLNA renderers;
- failed target command, natural completion, stop, timeout, and app shutdown remove the temporary
  file and token;
- upload size is bounded by an implementation constant and oversized uploads fail before playback.

**Step 2: Run focused tests**

```bash
pytest tests/test_playback_files.py -q
```

Expected: module/routes are absent.

**Step 3: Implement `EphemeralMediaStore`**

Use a process-owned temporary directory and opaque token map. Store only current playback files;
do not create a database, asset model, user configuration, or permanent cache. Mount transaction
creation, one-time raw upload, and renderer media GET routes on the existing aiohttp application.

**Step 4: Verify and commit**

```bash
pytest tests/test_playback_files.py tests/test_speaker_play_url.py -q
git add miair/playback/files.py miair/playback/service.py miair/web/api_v1.py miair/app.py tests/test_playback_files.py
git commit -m "feat: play ephemeral audio files"
```

### Task 6: Add the fixed-format PCM WebSocket input

**Files:**
- Create: `miair/playback/streams.py`
- Create: `tests/test_playback_streams.py`
- Modify: `miair/playback/service.py`
- Modify: `miair/web/api_v1.py`
- Modify: `miair/app.py`

**Step 1: Write stream tests**

Cover:

- create requires `s16le`, 48000 Hz, and two channels;
- create returns an opaque `stream_id` and URL derived from the request-visible host;
- the first binary frame reaches `CastFabricLiveAudioSink.write()` unchanged;
- text frames, a second writer, unknown stream, and write-before-open fail;
- the current sink's bounded queue/backpressure behavior remains intact;
- WebSocket close, target stop, output pull failure, and app shutdown stop both sink and session;
- two target IDs receive isolated sinks and tokens.

**Step 2: Verify failure**

```bash
pytest tests/test_playback_streams.py -q
```

Expected: module/routes are absent.

**Step 3: Implement `PcmStreamRegistry`**

Each active stream owns one `CastFabricLiveAudioSink`, one writer, one `stream_id`, and one MCP
media session. Reuse the target controller and configured hostname. Do not add format negotiation,
jitter configuration, transcoding, or persistence.

**Step 4: Verify and commit**

```bash
pytest tests/test_playback_streams.py tests/test_miplay_sink.py tests/test_dlna_output_poc.py -q
git add miair/playback/streams.py miair/playback/service.py miair/web/api_v1.py miair/app.py tests/test_playback_streams.py
git commit -m "feat: accept agent PCM streams"
```

### Task 7: Embed Streamable HTTP MCP on the existing listener

**Files:**
- Create: `miair/mcp/__init__.py`
- Create: `miair/mcp/server.py`
- Create: `miair/mcp/aiohttp_transport.py`
- Create: `tests/test_mcp_server.py`
- Create: `tests/test_mcp_transport.py`
- Modify: `miair/app.py`
- Modify: `miair/web/api.py`
- Modify: `pyproject.toml`

**Step 1: Add the official protocol dependency**

Use Python `>=3.10`, `mcp>=2.1.1,<3`, the existing aiohttp runtime, and the SDK's stateless
Streamable HTTP application with JSON responses. Do not add another executable or service.

**Step 2: Write failing MCP tool tests**

Assert the exact 11 tool names, required `target_id`, structured results, stable business error
conversion, and tool descriptions that tell the model to call `list_outputs` when it lacks an exact
ID. Test `play_file` returns a bounded same-origin upload transaction and `open_pcm_stream` returns
only the fixed PCM format.

**Step 3: Implement handlers against application services**

Use the official SDK's tool registration and protocol handling. Tool handlers call runtime,
discovery, target-update, playback, file-store, and stream-registry services directly; they do not
make loopback HTTP requests and do not import concrete output protocols.

**Step 4: Attach the official ASGI app to aiohttp**

Configure stateless HTTP and JSON responses. Add a narrow adapter for `/mcp` that faithfully maps
method, path, headers, body, status, response headers, and lifecycle into the official SDK ASGI app.
Reject unsupported GET streaming with 405 rather than implementing SSE. Preserve Origin/Host
validation. Do not implement JSON-RPC or MCP message dispatch manually.

**Step 5: Test with the official client**

```bash
pytest tests/test_mcp_server.py tests/test_mcp_transport.py -q
```

Expected: the official Streamable HTTP client initializes, lists tools, calls every read-only tool,
and receives typed errors through `http://127.0.0.1:<test-port>/mcp`; no second socket is opened.

**Step 6: Commit**

```bash
git add miair/mcp miair/app.py miair/web/api.py pyproject.toml tests/test_mcp_server.py tests/test_mcp_transport.py
git commit -m "feat: embed CastFabric MCP endpoint"
```

### Task 8: Create the CastFabric Agent Skill and Node helper

**Files:**
- Create: `skills/castfabric/SKILL.md`
- Create: `skills/castfabric/agents/openai.yaml`
- Create: `skills/castfabric/references/playlist-schema.md`
- Create: `skills/castfabric/scripts/castfabric.mjs`
- Create: `skills/castfabric/tests/castfabric.test.mjs`

**Step 1: Initialize the skill package**

Use the bundled skill initializer for the directory skeleton, then replace all scaffold text. Keep
automatic invocation enabled. The description must trigger for CastFabric speaker discovery,
playback, local audio files, PCM streaming, and playlists, but not for generic media editing.

**Step 2: Write Node tests first**

Use `node:test` and local fake HTTP/WebSocket servers. Cover:

- MCP initialize/list/scan/update calls over Streamable HTTP;
- URL playback and one-time raw file upload;
- safe local path resolution;
- FFmpeg command arguments produce `pcm_s16le`, 48000 Hz, two channels, and `-re` for finite input;
- stdin streaming omits `-re`;
- binary stdout chunks reach WebSocket in order;
- SIGINT/SIGTERM close input, stop the target, and reap FFmpeg;
- playlist ordering, `--loop`, pause handling, and explicit runner stop;
- errors use nonzero exit status and never print media bytes.

**Step 3: Implement one dependency-free helper**

Use Node 22 built-in `fetch`, `WebSocket`, `child_process`, and filesystem APIs.
Require FFmpeg only for `stream`; management, URL, file, control, and playlists must work without it.

**Step 4: Write the Skill instructions**

The Skill must enforce these choices:

1. call MCP `list_outputs` before guessing a target ID;
2. use MCP at the configured CastFabric `/mcp` URL for management, URL playback, and controls;
3. use helper `play-file` for Agent-local files; it calls MCP `play_file` and uploads bytes to the
   returned one-time same-origin URL;
4. use direct file playback for normal files and `stream` only for live/continuous sources;
5. keep playlists client-side and stop the runner before stopping the output.

**Step 5: Validate and commit**

```bash
node --test skills/castfabric/tests/*.test.mjs
python /Users/wang/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/castfabric
git add skills/castfabric
git commit -m "feat: add CastFabric Agent skill"
```

### Task 9: Add the AI Access console page

**Files:**
- Modify: `miair/web/static/index.html`
- Modify: `miair/web/static/console.css`
- Modify: `miair/web/static/console.js`
- Modify: `tests/test_console_contract.py`
- Create: `docs/design/contracts/castfabric-ai-access.md`

**Step 1: Write the UI implementation contract**

Record NameThatUI vocabulary and platform mapping:

- navigation item;
- service status card;
- client tablist/tab/tabpanel;
- read-only code block;
- copy button;
- polite live region;
- Skill install card;
- verification callout.

Reuse current visual tokens. Specify desktop/mobile layout, loading/ready/unavailable/copy-success/
copy-error states, keyboard interaction, focus behavior, text overflow, and reduced-motion behavior.

**Step 2: Add failing DOM/contract tests**

Assert bilingual copy, semantic buttons/tabs, accessible labels/live region, no hard-coded development
IP, and no TTS/playlist settings. Assert the generated verification prompt explicitly says not to
play sound.

**Step 3: Implement the page**

Generate the MCP URL from current browser origin. Generate client commands:

```text
codex mcp add --url <origin>/mcp castfabric
claude mcp add --transport http castfabric <origin>/mcp
```

Do not expose an editable endpoint field in the first release. Provide copy command, copy prompt,
and Skill install content.

**Step 4: Run contract tests**

```bash
pytest tests/test_console_contract.py -q
```

Expected: all UI contract checks pass.

**Step 5: Perform DesignQM verification**

Capture desktop and mobile screenshots for ready, unavailable, and copy-success states. Record D1-D6
evidence in the implementation contract and fix every observed visual/interaction defect before
commit.

**Step 6: Commit**

```bash
git add miair/web/static tests/test_console_contract.py docs/design/contracts/castfabric-ai-access.md
git commit -m "feat: add AI connection guide"
```

### Task 10: Add CI and automated end-to-end coverage

**Files:**
- Modify: `.github/workflows/test.yml`
- Modify: `pyproject.toml` only if root test extras need shared test dependencies
- Create: `tests/test_agent_audio_e2e.py`

**Step 1: Add a fake physical DMR end-to-end test**

Start CastFabric with a fake DLNA output, then drive:

1. scan/list/update target;
2. URL play and control;
3. one-time MP3/WAV upload whose generated HTTP URL is pulled by the fake DMR;
4. PCM WebSocket whose binary samples arrive at the fake DMR stream;
5. stop and cleanup.

**Step 2: Add CI jobs/steps**

- run embedded MCP protocol and transport tests;
- run Node 22 helper tests;
- validate the Skill package;
- retain existing Python tests and container smoke test.

**Step 3: Run all local gates**

```bash
pytest -q
node --test skills/castfabric/tests/*.test.mjs
python /Users/wang/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/castfabric
docker build -t castfabric:agent-audio-test .
```

Expected: all tests pass and the image builds.

**Step 4: Commit**

```bash
git add .github/workflows/test.yml pyproject.toml tests/test_agent_audio_e2e.py
git commit -m "test: verify agent audio end to end"
```

### Task 11: Verify with real local Agents and the Home Server

**Files:**
- Create or update: `docs/testing/castfabric-agent-audio-checklist.md`

**Step 1: Deploy a candidate without replacing rollback**

Build/publish a candidate image, preserve the known-good container/image, and deploy on the Home
Server using the existing host-network topology. Do not change router/proxy settings.

**Step 2: Verify the MCP protocol independently**

- list tools and call `list_outputs` with MCP Inspector;
- connect Codex and Claude Code directly to `http://<home-server>:9988/mcp`;
- confirm both identify the same `target_id` values;
- ask each Agent to scan and list only; confirm no sound plays.

**Step 3: Verify real audio**

- URL playback;
- local MP3 file upload/play;
- Node helper streaming the same file as PCM;
- stdin-generated PCM;
- two-item ordered playlist and loop cancellation;
- pause, stop, and volume;
- target offline and rediscovery recovery;
- existing DLNA, AirPlay, and MiPlay regression checks.

Record whether the physical renderer fetched the temporary/file/PCM URL and whether sound was heard.
Do not claim improved live-stream latency.

**Step 4: Roll back on any product-path regression**

Stop the candidate and restore the retained image if existing receiver discovery or sound output
regresses. Keep diagnostic logs but redact credentials, full media URLs, and tokens.

**Step 5: Commit the evidence**

```bash
git add docs/testing/castfabric-agent-audio-checklist.md
git commit -m "test: record agent audio verification"
```

### Task 12: Migrate, document, and release after POC passes

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/prototypes/castfabric-landing-v1.html`
- Modify: `.github/workflows/build.yml`
- Modify: `.github/workflows/pages.yml` if canonical URLs are embedded
- Modify: `docker-compose.yml`
- Modify: repository metadata and Pages configuration

**Step 1: Create the canonical organization repository**

Create independent `DjangoAILab/CastFabric`, preserve Git history and copyright notices, push the
verified main branch and CastFabric tags, and change local `origin`. Keep the old repository as an
archived migration pointer; do not delete it during this release.

**Step 2: Update package and Pages namespaces**

Publish `ghcr.io/djangoailab/castfabric`. Update canonical URLs, badges, Docker examples, page
metadata, and generated MCP/Skill installation source. Decide explicitly whether to dual-publish
the legacy GHCR namespace or document the alpha namespace change.

**Step 3: Update truthful product copy**

Describe MCP and Skill as supported only after the real-agent and real-speaker checklist passes.
Keep the input/output protocol matrix, MiAir acknowledgements, and the approximately four-second
live bridge limitation.

**Step 4: Run release gates**

```bash
pytest -q
node --test skills/castfabric/tests/*.test.mjs
docker build -t castfabric:release-candidate .
git diff --check
```

Expected: all automated gates pass; Home Server checklist has no unresolved product-path failure.

**Step 5: Merge and release**

Open a feature PR, require green CI, merge to `main`, publish the next prerelease, verify GHCR pull
on amd64/arm64 metadata, verify GitHub Pages, and repeat the read-only MCP connection check from the
published instructions.

## Final acceptance criteria

- One stable `target_id` is used by management, playback, controls, MCP, Skill, sessions, and UI.
- An Agent can list, scan, add/enable, disable, and rename an output using MCP.
- An Agent can play an accessible URL and a local file on a selected output.
- The Node helper can turn file/URL/stdin into fixed PCM and feed the existing live sink.
- The Node helper can play ordered and looping client-side playlists and stop without advancing.
- Existing DLNA, AirPlay, and MiPlay receiver paths still discover and produce sound.
- Console installation content connects Codex and Claude Code directly to the embedded `/mcp`
  endpoint and performs a silent read-only check.
- Home Server deployment remains one CastFabric process/container and exposes no new listening port.
- No TTS, media library, server playlist, queue, new playback policy, or new product setting is added.
- README, landing page, GHCR, Pages, and organization repository describe only verified behavior.
