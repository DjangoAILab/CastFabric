"""CLI diagnostics and offline end-to-end validation for MiPlay."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import struct

from .mdns import scan_miplay
from .media import RecordingPcmSink
from .receiver import MiPlayReceiver
from .simulator import MiPlaySourceSimulator


async def self_test(duration: float = 0.5) -> dict:
    sink = RecordingPcmSink()
    receiver = MiPlayReceiver(
        host="127.0.0.1",
        port=0,
        sink_factory=lambda: sink,
        advertise=False,
    )
    await receiver.start()
    try:
        source = MiPlaySourceSimulator(
            target_host="127.0.0.1",
            target_port=receiver.port,
            duration=duration,
        )
        result = await source.run()
        await asyncio.wait_for(receiver.wait_for_idle(), timeout=5)
        diagnostics = receiver.diagnostics()
    finally:
        await receiver.stop()
    pcm = b"".join(sink.chunks)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm) if pcm else ()
    peak = max((abs(value) for value in samples), default=0)
    passed = bool(
        result.control_opened
        and result.rtsp_ready
        and result.media_frames
        and pcm
        and peak > 500
    )
    return {
        "passed": passed,
        "control_opened": result.control_opened,
        "rtsp_ready": result.rtsp_ready,
        "media_frames": result.media_frames,
        "notifications": result.notifications,
        "pcm_bytes": len(pcm),
        "pcm_peak": peak,
        "sample_rate": sink.sample_rate,
        "channels": sink.channels,
        "receiver": diagnostics,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openxiaocast-miplay",
        description="Discover and validate OpenXiaoCast MiPlay endpoints.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    scan = subcommands.add_parser("scan", help="scan the LAN for MiPlay services")
    scan.add_argument("--timeout", type=float, default=3.0)

    simulate = subcommands.add_parser(
        "simulate", help="push an offline AAC test tone to a receiver"
    )
    simulate.add_argument("--target", required=True)
    simulate.add_argument("--port", type=int, default=8899)
    simulate.add_argument("--duration", type=float, default=0.5)
    simulate.add_argument("--frequency", type=int, default=440)

    test = subcommands.add_parser(
        "self-test", help="run the complete receiver/source loopback"
    )
    test.add_argument("--duration", type=float, default=0.5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "scan":
        devices = scan_miplay(args.timeout)
        payload = [
            {
                "name": device.friendly_name,
                "address": device.address,
                "control_port": device.control_port,
                "device_id": str(device.device_id),
                "security_mode": device.security_mode,
                "supports_audio": device.supports_audio,
            }
            for device in devices
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "simulate":
        result = asyncio.run(
            MiPlaySourceSimulator(
                target_host=args.target,
                target_port=args.port,
                duration=args.duration,
                tone_frequency=args.frequency,
            ).run()
        )
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
        return 0
    result = asyncio.run(self_test(args.duration))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
