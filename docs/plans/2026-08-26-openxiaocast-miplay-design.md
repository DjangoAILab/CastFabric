# OpenXiaoCast MiPlay Receiver Design

## Objective

Extend MiAir into OpenXiaoCast, a multi-protocol gateway for Xiaomi AI
speakers. The first new input is a MiPlay-compatible receiver that a Xiaomi
phone can discover and open. Received AAC/WFD audio is decoded to PCM and fed
into the same live HTTP audio path already used to play AirPlay audio on a
configured Xiaomi speaker.

The initial implementation is local-only and must not be pushed. It uses
public protocol observations from `SUlTlUS/openMiPlay` and
`SUlTlUS/MiPlayForWindows` as research references. Those repositories do not
currently declare a reusable license, so a future public release must either
obtain permission or retain a clean, independently maintained implementation.

## Architecture

```text
Xiaomi/HyperOS MiPlay source          Offline source simulator
              \                        /
               mDNS + TCP 8899 + WFD
                         |
                 MiPlayReceiver
          +--------------+--------------+
          |              |              |
       identity       command       reverse WFD
       announcer       session       RTSP client
                                          |
                                  RTP/MPEG-TS/AAC
                                          |
                                   ffmpeg decoder
                                          |
                                      PCM sink
                         +----------------+---------------+
                         |                                |
                  Recording/Test sink            MiAirLiveAudioSink
                                                        |
                                           AudioStreamServer + play_url
                                                        |
                                                 Xiaomi AI speaker
```

Protocol codecs and state machines are transport-free. Network orchestration
owns sockets, timeouts and cleanup. Audio delivery is expressed through a
small PCM sink interface so the complete wire path can be tested without a
Xiaomi account or physical speaker.

## Discovery identity

The receiver advertises `_mi-connect._udp.local.` with a distinct generated
identity rather than impersonating an existing speaker. The TXT record exposes
MiPlay application id 5, device class 4, transport security capability and an
`appsData` container carrying the control port and gateway UUID. A bundled
scanner browses and parses the same service so discovery can be verified on a
LAN independently of a phone.

The production default control listener is TCP 8899. The mDNS SRV port remains
the observed MiConnect CoAP port 56666; the application-data payload carries
the legacy control endpoint. Tests use ephemeral ports and direct loopback
injection where multicast is unavailable.

## Control path

Version one implements the captured legacy-clear receiver behavior:

1. Send one numeric `0x0028` challenge.
2. Verify the same-sequence `0x0029` HMAC-SHA1 response.
3. Acknowledge source version, device information, source identity, account,
   mirror mode, volume, state and heartbeat commands.
4. Accept `setPlaySource` and a NUL-terminated `Open` payload.
5. Parse `wfd://<source-ip>:<port>?mirrorMode=1` and create the three reverse
   TCP connections used by the captured WFD profile.

Unexpected or modern Safety frames are retained as redacted diagnostics and
stop the legacy session cleanly. Known SafetyAuth/SafetyData captured vectors
may be added as pure codecs, but current-phone interoperability is not claimed
until a real K60 session is observed.

## WFD and media path

The first reverse TCP connection performs the bidirectional RTSP handshake:
OPTIONS, capability query, selected AAC parameters, SETUP trigger, SETUP,
PLAY and TIME_OFFSET. The second connection is held as the observed auxiliary
channel. The third carries `$` plus a 24-bit length and an RTP packet.

Only RTP payload type 33 is accepted. Its payload must be aligned MPEG-TS.
MPEG-TS bytes are streamed to a bounded ffmpeg subprocess that outputs
48 kHz, stereo, signed 16-bit little-endian PCM. Process stderr is drained,
PCM delivery is backpressured, and all sockets/processes are closed when the
control session ends.

## Offline validation

The repository includes a source simulator that discovers the receiver,
completes the control session, acts as the WFD source, and streams a generated
AAC sine tone. The self-test verifies:

- parseable mDNS identity and MiPlay capability fields;
- complete legacy command progression through `Open`;
- complete reverse RTSP/WFD progression through `PLAY`;
- valid RTP/MPEG-TS ingestion;
- decoded non-silent PCM at the expected format and approximate tone
  frequency;
- the same PCM is consumable through the live HTTP WAV stream.

Real-device validation remains a separate gate for mDNS visibility, security
mode, command variants and audible M01 playback.

## Product and release

The public-facing product name becomes OpenXiaoCast while the Python package
and command remain `miair` for the first protocol release. This avoids mixing
protocol work with a breaking import/configuration migration. Docker images
are named from the GitHub repository instead of hard-coding `miair`.

CI builds and tests pull requests without publishing. Main builds and semantic
version tags publish multi-architecture GHCR images. Docker deployments require
host networking for multicast discovery and expose health diagnostics through
the existing web service.

