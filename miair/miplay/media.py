"""MiPlay WFD media framing, RTP validation and MPEG-TS audio decoding."""

from __future__ import annotations

import asyncio
import inspect
import logging
import struct
import time
from dataclasses import dataclass
from typing import Protocol


MEDIA_MAGIC = 0x24
MEDIA_HEADER_SIZE = 4
MAX_MEDIA_PAYLOAD = 0xFFFFFF
RTP_HEADER_SIZE = 12
RTP_MPEGTS_PAYLOAD_TYPE = 33
MPEGTS_PACKET_SIZE = 188
MAX_TS_PACKETS_PER_RTP = 7


log = logging.getLogger("miair")

# FFmpeg otherwise spends roughly five seconds probing a real-time MPEG-TS
# stream before emitting its first decoded sample. MiPlay always gives us a
# validated MPEG-TS/AAC stream, so a small probe is sufficient and avoids
# adding on-demand playback latency.
FFMPEG_LOW_LATENCY_INPUT_ARGS = (
    "-flags",
    "low_delay",
    "-probesize",
    "4096",
    "-analyzeduration",
    "0",
)


class MediaProtocolError(ValueError):
    pass


def encode_media_frame(payload: bytes) -> bytes:
    payload = bytes(payload)
    if not payload or len(payload) > MAX_MEDIA_PAYLOAD:
        raise MediaProtocolError("media payload length out of range")
    return bytes([MEDIA_MAGIC]) + len(payload).to_bytes(3, "big") + payload


class MediaFrameBuffer:
    def __init__(self, maximum: int = MAX_MEDIA_PAYLOAD):
        self.maximum = maximum
        self._buffer = bytearray()

    def feed(self, data: bytes | bytearray | memoryview) -> list[bytes]:
        self._buffer.extend(data)
        frames: list[bytes] = []
        while len(self._buffer) >= MEDIA_HEADER_SIZE:
            if self._buffer[0] != MEDIA_MAGIC:
                self._buffer.clear()
                raise MediaProtocolError("invalid media-frame magic")
            length = int.from_bytes(self._buffer[1:4], "big")
            if not length or length > self.maximum:
                self._buffer.clear()
                raise MediaProtocolError("media payload length exceeds safety limit")
            frame_length = MEDIA_HEADER_SIZE + length
            if len(self._buffer) < frame_length:
                break
            frames.append(bytes(self._buffer[MEDIA_HEADER_SIZE:frame_length]))
            del self._buffer[:frame_length]
        return frames


@dataclass(frozen=True, slots=True)
class RtpMpegTsPacket:
    sequence: int
    timestamp: int
    ssrc: int
    marker: bool
    transport_stream: bytes


def encode_rtp_mpegts(
    sequence: int,
    timestamp: int,
    ssrc: int,
    transport_stream: bytes,
    *,
    marker: bool = True,
) -> bytes:
    payload = bytes(transport_stream)
    _validate_transport_stream(payload)
    if len(payload) > MPEGTS_PACKET_SIZE * MAX_TS_PACKETS_PER_RTP:
        raise MediaProtocolError("RTP MPEG-TS payload exceeds captured packet limit")
    if not 0 <= sequence <= 0xFFFF or not 0 <= timestamp <= 0xFFFFFFFF or not 0 <= ssrc <= 0xFFFFFFFF:
        raise MediaProtocolError("RTP header field out of range")
    header = struct.pack(
        ">BBHII",
        0x80,
        (0x80 if marker else 0) | RTP_MPEGTS_PAYLOAD_TYPE,
        sequence,
        timestamp,
        ssrc,
    )
    return header + payload


def decode_rtp_mpegts(packet: bytes | bytearray | memoryview) -> RtpMpegTsPacket:
    data = bytes(packet)
    if len(data) < RTP_HEADER_SIZE + MPEGTS_PACKET_SIZE:
        raise MediaProtocolError("RTP packet is truncated")
    first, second, sequence, timestamp, ssrc = struct.unpack(">BBHII", data[:12])
    if first != 0x80:
        raise MediaProtocolError("unsupported RTP header flags")
    payload_type = second & 0x7F
    if payload_type != RTP_MPEGTS_PAYLOAD_TYPE:
        raise MediaProtocolError(f"unsupported RTP payload type {payload_type}")
    transport_stream = data[RTP_HEADER_SIZE:]
    _validate_transport_stream(transport_stream)
    return RtpMpegTsPacket(
        sequence,
        timestamp,
        ssrc,
        bool(second & 0x80),
        transport_stream,
    )


def _validate_transport_stream(payload: bytes) -> None:
    if not payload or len(payload) % MPEGTS_PACKET_SIZE:
        raise MediaProtocolError("MPEG-TS payload must contain complete 188-byte packets")
    for offset in range(0, len(payload), MPEGTS_PACKET_SIZE):
        if payload[offset] != 0x47:
            raise MediaProtocolError("MPEG-TS sync byte is missing")


class PcmSink(Protocol):
    async def start(self, sample_rate: int, channels: int, sample_width: int) -> None: ...
    async def write(self, data: bytes) -> None: ...
    async def stop(self) -> None: ...


class RecordingPcmSink:
    def __init__(self):
        self.sample_rate = 0
        self.channels = 0
        self.sample_width = 0
        self.chunks: list[bytes] = []
        self.started = False

    async def start(self, sample_rate: int, channels: int, sample_width: int) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.started = True

    async def write(self, data: bytes) -> None:
        if not self.started:
            raise RuntimeError("PCM sink is not started")
        self.chunks.append(bytes(data))

    async def stop(self) -> None:
        self.started = False


class FfmpegMpegTsDecoder:
    """Bounded ffmpeg subprocess converting streamed MPEG-TS AAC to PCM."""

    def __init__(self, sink: PcmSink, ffmpeg: str = "ffmpeg"):
        self.sink = sink
        self.ffmpeg = ffmpeg
        self.process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stopped = False
        self._started_at: float | None = None
        self._first_input_at: float | None = None
        self._first_pcm_at: float | None = None
        self._input_bytes = 0
        self._input_bytes_at_first_pcm: int | None = None

    async def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("decoder already started")
        self._started_at = time.monotonic()
        await self.sink.start(48_000, 2, 2)
        self.process = await asyncio.create_subprocess_exec(
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "mpegts",
            *FFMPEG_LOW_LATENCY_INPUT_ARGS,
            "-i",
            "pipe:0",
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-f",
            "s16le",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=128 * 1024,
        )
        self._stdout_task = asyncio.create_task(self._read_pcm())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def write(self, transport_stream: bytes) -> None:
        if self.process is None or self.process.stdin is None or self._stopped:
            raise RuntimeError("decoder is not running")
        _validate_transport_stream(bytes(transport_stream))
        if self._first_input_at is None:
            self._first_input_at = time.monotonic()
        self._input_bytes += len(transport_stream)
        self.process.stdin.write(transport_stream)
        await self.process.stdin.drain()

    def diagnostics(self) -> dict:
        first_pcm_ms = None
        if self._first_input_at is not None and self._first_pcm_at is not None:
            first_pcm_ms = round(
                (self._first_pcm_at - self._first_input_at) * 1000
            )
        return {
            "first_pcm_ms": first_pcm_ms,
            "input_bytes_at_first_pcm": self._input_bytes_at_first_pcm,
            "received_input": self._first_input_at is not None,
            "emitted_pcm": self._first_pcm_at is not None,
        }

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        process = self.process
        if process is None:
            await self.sink.stop()
            return
        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
            await process.stdin.wait_closed()
        return_code = await process.wait()
        if self._stdout_task:
            await self._stdout_task
        stderr = await self._stderr_task if self._stderr_task else b""
        await self.sink.stop()
        if return_code != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg MPEG-TS decoder failed: {message[-1000:]}")

    async def _read_pcm(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        while True:
            chunk = await self.process.stdout.read(16 * 1024)
            if not chunk:
                return
            if self._first_pcm_at is None:
                self._first_pcm_at = time.monotonic()
                self._input_bytes_at_first_pcm = self._input_bytes
                elapsed_ms = (
                    (self._first_pcm_at - self._first_input_at) * 1000
                    if self._first_input_at is not None
                    else 0
                )
                log.info("MiPlay FFmpeg 首个 PCM: MPEG-TS 输入后 %.0fms", elapsed_ms)
            result = self.sink.write(chunk)
            if inspect.isawaitable(result):
                await result

    async def _read_stderr(self) -> bytes:
        assert self.process is not None and self.process.stderr is not None
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await self.process.stderr.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            while total > 64 * 1024 and chunks:
                total -= len(chunks.pop(0))
        return b"".join(chunks)
