"""Async MiPlay receiver runtime joining control, WFD and PCM delivery."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import logging
import secrets
import socket
from collections.abc import Awaitable, Callable

from zeroconf import IPVersion, Zeroconf

from .control import LegacyReceiverSession
from .mdns import MiPlayIdentity
from .media import (
    FfmpegMpegTsDecoder,
    MediaFrameBuffer,
    PcmSink,
    decode_rtp_mpegts,
)
from .protocol import Command, CommandFrameBuffer, OpenDeviceRequest, ProtocolError
from .rtsp import ReceiverRtspSession, RtspBuffer


log = logging.getLogger("miair")


class MiPlayReceiver:
    """One TCP 8899-compatible receiver with a single active media source."""

    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 8899,
        sink_factory: Callable[[], PcmSink],
        identity: MiPlayIdentity | None = None,
        advertise: bool = True,
        advertise_address: str | None = None,
        ffmpeg: str = "ffmpeg",
        volume_setter: Callable[[int], Awaitable[object]] | None = None,
    ):
        self.host = host
        self.port = port
        self.sink_factory = sink_factory
        self.identity = identity
        self.advertise = advertise
        self.advertise_address = advertise_address
        self.ffmpeg = ffmpeg
        self.volume_setter = volume_setter
        self._server: asyncio.AbstractServer | None = None
        self._zeroconf: Zeroconf | None = None
        self._service_info = None
        self._session_tasks: set[asyncio.Task] = set()
        self._idle = asyncio.Event()
        self._idle.set()
        self._active_session = False
        self._last_session: dict | None = None
        self._pending_volume: int | None = None
        self._volume_event = asyncio.Event()
        self._volume_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("MiPlay receiver is already running")
        self._server = await asyncio.start_server(
            self._accept_control, self.host, self.port, start_serving=True
        )
        socket_info = self._server.sockets[0].getsockname()
        self.port = int(socket_info[1])
        if self.advertise:
            address = self.advertise_address or self._default_advertise_address()
            identity = self.identity or MiPlayIdentity(address=address)
            identity = dataclasses.replace(
                identity, address=address, control_port=self.port
            )
            self.identity = identity
            self._service_info = identity.service_info()
            self._zeroconf = Zeroconf(
                interfaces=[address],
                ip_version=IPVersion.V4Only,
            )
            await asyncio.to_thread(
                self._zeroconf.register_service, self._service_info
            )
        if self.volume_setter is not None:
            self._pending_volume = None
            self._volume_event.clear()
            self._volume_task = asyncio.create_task(self._volume_worker())
        log.info("MiPlay 接收服务已启动: %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for task in list(self._session_tasks):
            task.cancel()
        if self._session_tasks:
            await asyncio.gather(*self._session_tasks, return_exceptions=True)
        if self._volume_task is not None:
            self._volume_task.cancel()
            await asyncio.gather(self._volume_task, return_exceptions=True)
            self._volume_task = None
        if self._zeroconf is not None:
            if self._service_info is not None:
                await asyncio.to_thread(
                    self._zeroconf.unregister_service, self._service_info
                )
            await asyncio.to_thread(self._zeroconf.close)
            self._zeroconf = None
            self._service_info = None
        self._idle.set()

    async def wait_for_idle(self) -> None:
        await self._idle.wait()

    def diagnostics(self) -> dict:
        return {
            "running": self._server is not None,
            "listen_port": self.port,
            "advertising": self._service_info is not None,
            "active_session": self._active_session,
            "last_session": dict(self._last_session) if self._last_session else None,
        }

    async def _accept_control(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._session_tasks.add(task)
        self._idle.clear()
        peer = writer.get_extra_info("peername")
        local = writer.get_extra_info("sockname")
        if self._active_session:
            log.warning("MiPlay 拒绝并发发送端: %s", peer)
            writer.close()
            await writer.wait_closed()
            self._session_tasks.discard(task)
            if not self._session_tasks:
                self._idle.set()
            return
        self._active_session = True
        write_lock = asyncio.Lock()
        challenge = str(secrets.randbelow(10**15 - 10**14) + 10**14).encode()
        local_endpoint = (str(local[0]), int(local[1])) if local else None
        peer_endpoint = (str(peer[0]), int(peer[1])) if peer else None
        session = LegacyReceiverSession(
            challenge=challenge,
            local_endpoint=local_endpoint,
            peer_endpoint=peer_endpoint,
        )
        report = {
            "peer": str(peer[0]) if peer else "unknown",
            "authenticated": False,
            "control_frames": 0,
            "control_trace": [],
            "safety": None,
            "rtsp_ready": False,
            "wfd_restarts": 0,
            "media_frames": 0,
            "media_bytes": 0,
            "decoder": None,
            "error": None,
        }
        wfd_task: asyncio.Task | None = None

        async def write_control(writes: list[bytes]) -> None:
            if not writes or writer.is_closing():
                return
            async with write_lock:
                writer.writelines(writes)
                await writer.drain()

        try:
            await write_control(session.start())
            decoder = CommandFrameBuffer()
            while True:
                data = await reader.read(16 * 1024)
                if not data:
                    break
                for frame in decoder.feed(data):
                    report["control_frames"] += 1
                    report["control_trace"].append(
                        {
                            "command": f"0x{frame.command:04x}",
                            "sequence": frame.sequence,
                            "payload_bytes": len(frame.payload),
                        }
                    )
                    if len(report["control_trace"]) > 64:
                        del report["control_trace"][:-64]
                    result = session.process(frame)
                    report["authenticated"] = session.authenticated
                    report["safety"] = session.safety_diagnostics()
                    if result.writes:
                        await write_control(result.writes)
                    if not result.accepted:
                        raise ProtocolError(result.reason)
                    if frame.command == Command.SET_VOLUME:
                        self._queue_volume(session.volume)
                    if result.open_request is not None:
                        if wfd_task is not None:
                            if not wfd_task.done():
                                wfd_task.cancel()
                            await asyncio.gather(wfd_task, return_exceptions=True)
                            report["wfd_restarts"] += 1
                        wfd_task = asyncio.create_task(
                            self._run_wfd(
                                result.open_request,
                                session,
                                write_control,
                                report,
                            )
                        )
            if wfd_task is not None:
                await wfd_task
        except asyncio.CancelledError:
            if wfd_task:
                wfd_task.cancel()
            raise
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            log.warning("MiPlay 会话结束: %s", report["error"])
            if wfd_task and not wfd_task.done():
                wfd_task.cancel()
                await asyncio.gather(wfd_task, return_exceptions=True)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, BrokenPipeError):
                pass
            self._last_session = report
            self._active_session = False
            self._session_tasks.discard(task)
            if not self._session_tasks:
                self._idle.set()

    def _queue_volume(self, volume: int) -> None:
        """Coalesce rapid key presses while preserving the newest volume."""
        if self.volume_setter is None:
            return
        self._pending_volume = volume
        self._volume_event.set()

    async def _volume_worker(self) -> None:
        assert self.volume_setter is not None
        while True:
            await self._volume_event.wait()
            self._volume_event.clear()
            volume = self._pending_volume
            if volume is None:
                continue
            try:
                result = self.volume_setter(volume)
                if inspect.isawaitable(result):
                    result = await result
                if result is False:
                    log.warning("MiPlay 音量下发失败: %s%%", volume)
                else:
                    log.info("MiPlay 音量已同步到音箱: %s%%", volume)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("MiPlay 音量下发异常 (%s%%): %s", volume, exc)

    async def _run_wfd(
        self,
        request: OpenDeviceRequest,
        control_session: LegacyReceiverSession,
        write_control,
        report: dict,
    ) -> None:
        connections = []
        decoder: FfmpegMpegTsDecoder | None = None
        rtsp_task: asyncio.Task | None = None
        try:
            for _ in range(3):
                connections.append(
                    await asyncio.wait_for(
                        asyncio.open_connection(request.host, request.port), timeout=5
                    )
                )
            (rtsp_reader, rtsp_writer), (_, aux_writer), (media_reader, media_writer) = connections
            ready = asyncio.get_running_loop().create_future()
            rtsp_task = asyncio.create_task(
                self._run_rtsp_control(
                    rtsp_reader, rtsp_writer, request.host, ready
                )
            )
            await asyncio.wait_for(asyncio.shield(ready), timeout=8)
            report["rtsp_ready"] = True

            decoder = FfmpegMpegTsDecoder(self.sink_factory(), self.ffmpeg)
            await decoder.start()
            media_buffer = MediaFrameBuffer()
            first_media = True
            while True:
                data = await media_reader.read(32 * 1024)
                if not data:
                    break
                for wire_rtp in media_buffer.feed(data):
                    packet = decode_rtp_mpegts(wire_rtp)
                    report["media_frames"] += 1
                    report["media_bytes"] += len(packet.transport_stream)
                    await decoder.write(packet.transport_stream)
                    if first_media:
                        first_media = False
                        await write_control(control_session.media_started())
            await decoder.stop()
            report["decoder"] = decoder.diagnostics()
            decoder = None
        finally:
            if decoder is not None:
                try:
                    await decoder.stop()
                except Exception:
                    pass
                report["decoder"] = decoder.diagnostics()
            if rtsp_task is not None:
                rtsp_task.cancel()
                await asyncio.gather(rtsp_task, return_exceptions=True)
            for _, connection_writer in connections:
                connection_writer.close()
            for _, connection_writer in connections:
                try:
                    await connection_writer.wait_closed()
                except (ConnectionError, BrokenPipeError):
                    pass

    async def _run_rtsp_control(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        source_address: str,
        ready: asyncio.Future,
    ) -> None:
        session = ReceiverRtspSession(source_address)
        parser = RtspBuffer()
        try:
            while True:
                data = await reader.read(16 * 1024)
                if not data:
                    raise ConnectionError("WFD source closed RTSP control")
                for message in parser.feed(data):
                    transition = session.process(message)
                    if not transition.accepted:
                        raise ProtocolError(transition.reason)
                    if transition.writes:
                        writer.writelines(transition.writes)
                        await writer.drain()
                    if transition.ready and not ready.done():
                        ready.set_result(True)
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise

    def _default_advertise_address(self) -> str:
        if self.host not in {"0.0.0.0", "::", ""}:
            return self.host
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
