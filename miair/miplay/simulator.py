"""Offline Xiaomi-source simulator for full MiPlay receiver validation."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass

from .media import MPEGTS_PACKET_SIZE, encode_media_frame, encode_rtp_mpegts
from .protocol import (
    Command,
    CommandFrame,
    CommandFrameBuffer,
    encode_command,
    legacy_challenge_response,
)
from .rtsp import RtspBuffer, RtspMessage, encode_rtsp


class _CommandChannel:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.decoder = CommandFrameBuffer()
        self.pending: deque[CommandFrame] = deque()

    async def send(self, *frames: bytes) -> None:
        self.writer.writelines(frames)
        await self.writer.drain()

    async def read(self, timeout: float = 5) -> CommandFrame:
        while not self.pending:
            data = await asyncio.wait_for(self.reader.read(16 * 1024), timeout)
            if not data:
                raise ConnectionError("MiPlay control receiver closed")
            self.pending.extend(self.decoder.feed(data))
        return self.pending.popleft()


class _RtspChannel:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.decoder = RtspBuffer()
        self.pending: deque[RtspMessage] = deque()

    async def send(self, *messages: RtspMessage) -> None:
        self.writer.writelines([encode_rtsp(message) for message in messages])
        await self.writer.drain()

    async def read(self, timeout: float = 5) -> RtspMessage:
        while not self.pending:
            data = await asyncio.wait_for(self.reader.read(16 * 1024), timeout)
            if not data:
                raise ConnectionError("MiPlay RTSP receiver closed")
            self.pending.extend(self.decoder.feed(data))
        return self.pending.popleft()


@dataclass(frozen=True, slots=True)
class SimulationResult:
    control_opened: bool
    rtsp_ready: bool
    media_frames: int
    notifications: dict[str, int]


class MiPlaySourceSimulator:
    def __init__(
        self,
        *,
        target_host: str,
        target_port: int,
        source_host: str = "127.0.0.1",
        tone_frequency: int = 440,
        duration: float = 0.5,
        ffmpeg: str = "ffmpeg",
        volume: int | None = None,
    ):
        self.target_host = target_host
        self.target_port = target_port
        self.source_host = source_host
        self.tone_frequency = tone_frequency
        self.duration = duration
        self.ffmpeg = ffmpeg
        self.volume = volume

    async def run(self) -> SimulationResult:
        reverse_queue: asyncio.Queue = asyncio.Queue()
        close_handlers = asyncio.Event()

        async def accept_reverse(reader, writer):
            await reverse_queue.put((reader, writer))
            await close_handlers.wait()

        reverse_server = await asyncio.start_server(
            accept_reverse, self.source_host, 0
        )
        reverse_port = int(reverse_server.sockets[0].getsockname()[1])
        control_reader, control_writer = await asyncio.open_connection(
            self.target_host, self.target_port
        )
        control = _CommandChannel(control_reader, control_writer)
        reverse_connections = []
        notifications: dict[str, int] = {}
        media_frames = 0
        try:
            challenge = await control.read()
            if challenge.command != Command.LEGACY_CHALLENGE:
                raise RuntimeError("receiver did not start with legacy challenge")
            await control.send(
                encode_command(Command.SOURCE_VERSION, 0, b"1.0.1123012\0"),
                encode_command(
                    Command.LEGACY_CHALLENGE_ACK,
                    challenge.sequence,
                    legacy_challenge_response(challenge.payload),
                ),
                encode_command(Command.GET_DEVICE_INFO, 1),
            )
            await self._expect_commands(
                control, {Command.SOURCE_VERSION_ACK, Command.GET_DEVICE_INFO_ACK}
            )

            await control.send(
                encode_command(
                    Command.SET_LOCAL_DEVICE_INFO,
                    2,
                    b'{"sourceName":"OpenXiaoCast Offline Source"}',
                )
            )
            await self._expect(control, Command.SET_LOCAL_DEVICE_INFO_ACK)

            await control.send(
                encode_command(
                    Command.SET_LOCAL_DEVICE_INFO, 3, b'{"isSameAccount":0}'
                ),
                encode_command(Command.GET_MIRROR_MODE, 4),
                encode_command(Command.GET_VOLUME, 5),
                encode_command(Command.GET_MEDIA_INFO, 6),
                encode_command(Command.GET_STATE, 7),
            )
            await self._expect_commands(
                control,
                {
                    Command.SET_LOCAL_DEVICE_INFO_ACK,
                    Command.GET_MIRROR_MODE_ACK,
                    Command.GET_VOLUME_ACK,
                    Command.GET_MEDIA_INFO_ACK,
                    Command.GET_STATE_ACK,
                },
            )

            if self.volume is not None:
                await control.send(
                    encode_command(
                        Command.SET_VOLUME,
                        16,
                        self.volume.to_bytes(4, "big"),
                    )
                )
                await self._expect(control, Command.SET_VOLUME_ACK)

            await control.send(
                encode_command(
                    Command.SET_LOCAL_DEVICE_INFO,
                    8,
                    b'{"sourceName":"OpenXiaoCast Offline Source"}',
                ),
                encode_command(Command.GET_DEVICE_INFO, 9),
            )
            await self._expect_commands(
                control,
                {Command.SET_LOCAL_DEVICE_INFO_ACK, Command.GET_DEVICE_INFO_ACK},
            )
            await control.send(
                encode_command(
                    Command.SET_LOCAL_DEVICE_INFO, 10, b'{"isSameAccount":0}'
                )
            )
            await self._expect(control, Command.SET_LOCAL_DEVICE_INFO_ACK)
            await control.send(encode_command(Command.GET_MIRROR_MODE, 11))
            await self._expect(control, Command.GET_MIRROR_MODE_ACK)
            await control.send(encode_command(Command.HEARTBEAT, 12))
            await self._expect(control, Command.HEARTBEAT_ACK)

            await control.send(
                encode_command(
                    Command.SET_PLAY_SOURCE,
                    13,
                    b'{"ref_channel":"offline-self-test"}',
                ),
                encode_command(
                    Command.OPEN,
                    14,
                    f"wfd://{self.source_host}:{reverse_port}?mirrorMode=1\0".encode(),
                ),
            )

            for _ in range(3):
                reverse_connections.append(
                    await asyncio.wait_for(reverse_queue.get(), timeout=5)
                )
            rtsp = _RtspChannel(*reverse_connections[0])
            await self._run_rtsp(rtsp)

            await control.send(
                encode_command(
                    Command.SET_MEDIA_INFO,
                    15,
                    json.dumps(
                        {
                            "mTitle": "Offline tone",
                            "mSourceName": "OpenXiaoCast Offline Source",
                            "mDeviceState": 2,
                        },
                        separators=(",", ":"),
                    ).encode(),
                )
            )

            transport_stream = await self._generate_transport_stream()
            media_writer = reverse_connections[2][1]
            sequence = 0
            timestamp = 0
            maximum = MPEGTS_PACKET_SIZE * 7
            for offset in range(0, len(transport_stream), maximum):
                chunk = transport_stream[offset:offset + maximum]
                if not chunk:
                    continue
                rtp = encode_rtp_mpegts(
                    sequence,
                    timestamp,
                    0xDEADBEEF,
                    chunk,
                    marker=True,
                )
                media_writer.write(encode_media_frame(rtp))
                media_frames += 1
                sequence = (sequence + 1) & 0xFFFF
                timestamp = (timestamp + 1920) & 0xFFFFFFFF
            await media_writer.drain()
            media_writer.close()
            await media_writer.wait_closed()

            for _ in range(3):
                frame = await control.read(timeout=5)
                if frame.command == Command.NOTIFY:
                    label, value = self._decode_notify(frame.payload)
                    notifications[label] = value
                elif frame.command != Command.SET_MEDIA_INFO_ACK:
                    raise RuntimeError(
                        f"unexpected post-open command 0x{frame.command:04x}"
                    )

            return SimulationResult(True, True, media_frames, notifications)
        finally:
            control_writer.close()
            try:
                await control_writer.wait_closed()
            except (ConnectionError, BrokenPipeError):
                pass
            for _, writer in reverse_connections:
                if not writer.is_closing():
                    writer.close()
            for _, writer in reverse_connections:
                try:
                    await writer.wait_closed()
                except (ConnectionError, BrokenPipeError):
                    pass
            close_handlers.set()
            reverse_server.close()
            await reverse_server.wait_closed()

    async def _run_rtsp(self, channel: _RtspChannel) -> None:
        await channel.send(
            RtspMessage(
                "OPTIONS * RTSP/1.0",
                {
                    "CSeq": "1",
                    "Require": "org.wfa.wfd1.0",
                    "wfd_timer_server_port": "2130706433:36524",
                },
            )
        )
        initial = [await channel.read(), await channel.read()]
        receiver_options = next(
            item for item in initial if item.start_line.startswith("OPTIONS ")
        )
        if not any(item.start_line == "RTSP/1.0 200 OK" for item in initial):
            raise RuntimeError("receiver did not acknowledge source OPTIONS")
        await channel.send(
            RtspMessage(
                "RTSP/1.0 200 OK", {"CSeq": receiver_options.header("CSeq") or "1"}
            ),
            RtspMessage(
                "GET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0",
                {"CSeq": "2", "Content-Type": "text/parameters"},
                b"wfd_video_formats\r\nwfd_audio_codecs\r\nwfd_client_rtp_ports\r\n",
            ),
        )
        capability = await channel.read()
        if b"wfd_audio_codecs: AAC 00000001 00" not in capability.body:
            raise RuntimeError("receiver did not advertise AAC")
        await channel.send(
            RtspMessage(
                "SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0",
                {"CSeq": "3", "Content-Type": "text/parameters"},
                b"wfd_audio_codecs: AAC 00000001 00\r\n"
                b"wfd_client_rtp_ports: RTP/AVP/TCP;interleaved mode=play\r\n",
            )
        )
        await channel.read()
        await channel.send(
            RtspMessage(
                "SET_PARAMETER rtsp://localhost/wfd1.0 RTSP/1.0",
                {"CSeq": "4", "Content-Type": "text/parameters"},
                b"wfd_trigger_method: SETUP\r\n",
            )
        )
        trigger = [await channel.read(), await channel.read()]
        setup = next(item for item in trigger if item.start_line.startswith("SETUP "))
        await channel.send(
            RtspMessage(
                "RTSP/1.0 200 OK",
                {
                    "CSeq": setup.header("CSeq") or "2",
                    "Session": "588290182;timeout=60",
                    "Transport": "RTP/AVP/TCP;interleaved=0-1;",
                },
            )
        )
        play = await channel.read()
        if not play.start_line.startswith("PLAY "):
            raise RuntimeError("receiver did not issue PLAY")
        await channel.send(
            RtspMessage(
                "RTSP/1.0 200 OK",
                {"CSeq": "3", "Session": "588290182"},
            ),
            RtspMessage(
                "TIME_OFFSET rtsp://localhost/wfd1.0 RTSP/1.0",
                {"CSeq": "5", "TimeOffset": "9633364443"},
            ),
        )
        ready = await channel.read()
        if ready.start_line != "RTSP/1.0 200 OK" or ready.header("CSeq") != "5":
            raise RuntimeError("receiver did not acknowledge TIME_OFFSET")

    async def _generate_transport_stream(self) -> bytes:
        process = await asyncio.create_subprocess_exec(
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={self.tone_frequency}:sample_rate=48000:duration={self.duration}",
            "-ac",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "mpegts",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"ffmpeg tone generation failed: {stderr.decode(errors='replace')}"
            )
        if not stdout or len(stdout) % MPEGTS_PACKET_SIZE:
            raise RuntimeError("ffmpeg produced an invalid MPEG-TS stream")
        return stdout

    @staticmethod
    async def _expect(channel: _CommandChannel, expected: Command) -> CommandFrame:
        frame = await channel.read()
        if frame.command != expected:
            raise RuntimeError(
                f"expected command 0x{expected:04x}, got 0x{frame.command:04x}"
            )
        return frame

    @staticmethod
    async def _expect_commands(
        channel: _CommandChannel, expected: set[Command]
    ) -> list[CommandFrame]:
        frames = [await channel.read() for _ in expected]
        actual = {Command(frame.command) for frame in frames}
        if actual != expected:
            raise RuntimeError(f"unexpected command set: {actual}")
        return frames

    @staticmethod
    def _decode_notify(payload: bytes) -> tuple[str, int]:
        if not payload:
            raise RuntimeError("empty notify payload")
        length = payload[0]
        if len(payload) != length + 3 or payload[length + 1] != 3:
            raise RuntimeError("unsupported notify payload")
        return payload[1:1 + length].decode("ascii"), payload[-1]
