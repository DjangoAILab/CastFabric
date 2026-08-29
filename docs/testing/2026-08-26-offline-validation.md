# CastFabric MiPlay offline validation report

Commit under validation: `ea0fc9e` plus the Docker cache-boundary follow-up.

## Passed gates

- Python 3.12: `59 passed` with pytest async mode enabled.
- MiPlay loopback: legacy control authenticated, RTSP Ready, six media frames,
  73,728 bytes of non-silent 48 kHz stereo PCM, peak sample 2,974.
- Speaker output integration: valid WAV header and non-silent PCM reached the
  fake Xiaomi controller's HTTP client.
- LAN discovery: a live `_mi-connect._udp.local.` advertisement was found by
  `scan_miplay`; its UUID, `192.168.6.215` address and dynamic control port
  matched the running receiver.
- Docker arm64: image built successfully; the same MiPlay self-test passed
  inside the image.
- Container runtime: the configured health check reached `/api/status` and
  returned version `0.9.0a1` from a clean, account-free container.
- GitHub Actions: branch run `32920420502` completed successfully, including
  Python tests, offline wire self-test, Docker build and in-image self-test.

## Remaining external gate

No K60 or M01 was available during this run. Discovery by the phone, its
legacy-versus-Safety security selection and audible playback on the physical
speaker therefore remain explicitly unclaimed. The exact procedure and
redaction rules are in `miplay-real-device-checklist.md`.
