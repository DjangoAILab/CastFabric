# OpenXiaoCast Delivery Roadmap

This roadmap turns the MiPlay receiver work into independently verifiable
stages. Each stage has a concrete artifact, a promotion gate and a fallback;
passing an offline gate never substitutes for the final K60/M01 real-device
gate.

## Stage 0 — Protocol foundation (complete)

**Deliverables**

- MiPlay command framing, legacy challenge response and business payload
  codecs.
- MiConnect application-5 mDNS identity generation and parsing.
- Receiver-side legacy command state machine through `Open`.
- Receiver-side reverse WFD/RTSP state machine.
- RTP/MPEG-TS validation and ffmpeg AAC-to-PCM decoding.

**Gate:** deterministic protocol tests and a real ffmpeg tone decode pass.

**Status:** complete on `feat/miplay-receiver`.

## Stage 1 — Offline network loopback

**Deliverables**

- Async TCP 8899 receiver runtime with one active source session.
- Three reverse WFD connections: RTSP, auxiliary and media.
- Bounded socket/process cleanup, timeouts and redacted diagnostics.
- Source simulator that behaves like the captured Xiaomi legacy sender.
- `scan`, `simulate` and `self-test` diagnostic commands.

**Gate:** a simulator generates AAC tone traffic over real loopback sockets;
the receiver reaches RTSP Ready and records non-silent 48 kHz stereo PCM.

**Fallback:** retain the protocol transcript and media decoder tests separately
if an OS multicast restriction prevents the optional loopback mDNS assertion.

## Stage 2 — MiAir output integration

**Deliverables**

- Protocol-neutral live PCM sink wrapping the existing HTTP WAV stream.
- MiPlay lifecycle wired into the main application and selected speaker.
- Configuration switches, diagnostics and graceful restart behavior.
- AirPlay output regression coverage.

**Gate:** the full MiPlay wire loop writes PCM into a fake-controller-backed
HTTP stream, a client reads a valid WAV header plus non-silent audio, and no
physical Xiaomi account or speaker is needed.

**Fallback:** recording sink remains available to isolate MiPlay ingress from
speaker-cloud/API failures during real-device diagnosis.

## Stage 3 — Productization and release

**Deliverables**

- OpenXiaoCast product name in user-facing metadata and documentation while
  retaining the `miair` Python package/CLI compatibility boundary.
- Host-network Docker Compose example and health check.
- Pull-request test workflow.
- Main/tag multi-architecture GHCR publishing with repository-derived image
  names and semantic tags.
- No-license research-source disclosure and clean implementation boundary.

**Gate:** complete Python suite passes; Docker image builds; its health check,
CLI self-test prerequisites and configuration paths are inspectable without
secrets.

**Fallback:** keep the existing `miair` image alias documented for one release
if a repository rename would otherwise break installations.

## Stage 4 — K60 and M01 real-device certification

**Deliverables**

- K60 discovers the distinct OpenXiaoCast receiver identity.
- Redacted command transcript identifies legacy or modern Safety flow.
- Source reaches Open/RTSP Ready and transfers real application audio.
- M01 audibly plays the resulting live stream; latency and interruption
  behavior are measured.
- Compatibility matrix records HyperOS build, phone model, speaker model and
  outcome.

**Gate:** two consecutive cold-start casts complete without stale sessions or
manual service restarts.

**Escalation:** if K60 chooses SafetyAuth/SafetyData, preserve the captured
encrypted framing and implement that branch from verified endpoint-derived
vectors before changing the legacy path. If MiPlay ingress succeeds but M01 is
silent, diagnose only the downstream HTTP/speaker path using the recording
sink and direct stream client.

## Release sequence

1. Push every completed stage to `feat/miplay-receiver` with focused commits.
2. Keep CI green and avoid merging while Stage 4 is unverified.
3. After real-device certification, choose the public repository rename and
   image migration window.
4. Tag the first OpenXiaoCast preview only after the compatibility and license
   notes are complete.
