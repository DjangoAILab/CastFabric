# MiPlay K60/M01 real-device certification

This is the Stage 4 gate. Record versions and redacted outcomes, never Xiaomi
credentials, cookies, account IDs or unrelated packet payloads.

## 1. Prepare the receiver

1. Put the CastFabric host, K60 and M01 on the same non-isolated LAN/VLAN.
2. Use host networking and allow UDP 5353 plus TCP 8899 and ephemeral reverse
   WFD connections through the host firewall.
3. Select the M01 in the Web UI and confirm `启用妙播接收` is on.
4. Open `http://HOST:8300/api/miplay/status`; verify `running` is true and note
   the advertised name and port.
5. Run `openxiaocast-miplay scan --timeout 5` from a second LAN host. The
   CastFabric identity must appear with audio support.

## 2. Cast from K60

1. Cold-start CastFabric, unlock the K60 and open its system audio-output or
   妙播 device picker.
2. Select the distinct `CastFabric` entry, start a local audio track and keep
   it playing for at least 30 seconds.
3. Check `/api/miplay/status`. A successful legacy path reaches control Open,
   RTSP Ready and reports incoming media/PCM counters.
4. Confirm the M01 becomes audible, then exercise pause, resume, source
   disconnect and immediate reconnect.
5. Repeat the complete cold-start flow twice without manually restarting the
   service.

## 3. Record the compatibility result

Record: K60 model and HyperOS build, CastFabric commit/image digest, M01
hardware/firmware, discovery result, security mode, time-to-audio, approximate
latency, pause/resume behavior and both cold-start outcomes.

If the sender selects `SafetyAuth`/`SafetyData`, retain only redacted command
types, lengths and timing, then implement that verified branch separately. If
PCM counters advance but the M01 is silent, use the recording sink or a direct
HTTP stream client to isolate the downstream speaker path before changing the
MiPlay protocol implementation.
