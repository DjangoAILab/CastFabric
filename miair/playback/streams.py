"""Fixed-format PCM input sessions backed by the existing live audio sink."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from typing import Callable

from miair.runtime.models import IngressProtocol, SessionState
from miair.streaming.sink import CastFabricLiveAudioSink
from miair.targets import normalize_target_id


class PcmStreamError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class PcmStream:
    id: str
    target_id: str
    session_id: str
    sink: CastFabricLiveAudioSink
    writer_connected: bool = False


class PcmStreamRegistry:
    SAMPLE_FORMAT = "s16le"
    SAMPLE_RATE = 48000
    CHANNELS = 2
    SAMPLE_WIDTH = 2

    def __init__(
        self,
        playback_service,
        *,
        hostname: str,
        sink_factory: Callable = CastFabricLiveAudioSink,
        lifecycle_callback: Callable | None = None,
        id_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ):
        self.playback_service = playback_service
        self.hostname = hostname
        self.sink_factory = sink_factory
        self.lifecycle_callback = lifecycle_callback
        self.id_factory = id_factory
        self._streams: dict[str, PcmStream] = {}
        self._fallback_locks: dict[str, asyncio.Lock] = {}

    def _operation_lock(self, target_id: str) -> asyncio.Lock:
        lock_factory = getattr(self.playback_service, "operation_lock", None)
        if lock_factory is not None:
            return lock_factory(target_id)
        return self._fallback_locks.setdefault(target_id, asyncio.Lock())

    async def create(
        self,
        target_id: str,
        *,
        sample_format: str,
        sample_rate: int,
        channels: int,
    ) -> dict:
        if (
            sample_format != self.SAMPLE_FORMAT
            or sample_rate != self.SAMPLE_RATE
            or channels != self.CHANNELS
        ):
            raise PcmStreamError("UNSUPPORTED_PCM_FORMAT")
        normalized = normalize_target_id(target_id)
        async with self._operation_lock(normalized):
            controller = self.playback_service.controller_for(normalized)
            await self._stop_target_unlocked(normalized)
            before_session_begin = getattr(
                self.playback_service, "before_session_begin", None
            )
            if before_session_begin is not None:
                await before_session_begin(normalized)
            session = await self.playback_service.session_coordinator.begin(
                normalized,
                IngressProtocol.MCP,
                media_format="PCM s16le 48 kHz · 2 ch",
            )
            suite = self.playback_service.suite_registry.get(normalized)
            suite.current_session_id = session.id
            sink = self.sink_factory(self.hostname, controller)
            if self.lifecycle_callback is not None and hasattr(sink, "lifecycle_callback"):
                sink.lifecycle_callback = (
                    lambda event, details: self.lifecycle_callback(
                        normalized, event, details
                    )
                )
            if hasattr(sink, "output_owner"):
                sink.output_owner = lambda: (
                    getattr(
                        self.playback_service.session_coordinator.current(normalized),
                        "id",
                        None,
                    )
                    == session.id
                )
            stream_id = self.id_factory()
            stream = PcmStream(stream_id, normalized, session.id, sink)
            self._streams[stream_id] = stream
            try:
                await sink.start(self.SAMPLE_RATE, self.CHANNELS, self.SAMPLE_WIDTH)
            except Exception:
                self._streams.pop(stream_id, None)
                await self.playback_service.session_coordinator.end(
                    session.id, failed=True
                )
                if suite.current_session_id == session.id:
                    suite.current_session_id = None
                raise
            await self.playback_service.session_coordinator.transition(
                session.id, SessionState.PLAYING
            )
            return {
                "ok": True,
                "target_id": normalized,
                "session_id": session.id,
                "stream_id": stream_id,
                "stream_path": f"/api/v1/playback/streams/{stream_id}",
                "format": {
                    "sample_format": self.SAMPLE_FORMAT,
                    "sample_rate": self.SAMPLE_RATE,
                    "channels": self.CHANNELS,
                },
            }

    def claim_writer(self, stream_id: str) -> PcmStream:
        stream = self._streams.get(stream_id)
        if stream is None:
            raise PcmStreamError("STREAM_NOT_FOUND")
        if stream.writer_connected:
            raise PcmStreamError("STREAM_ALREADY_CONNECTED")
        stream.writer_connected = True
        return stream

    async def write(self, stream: PcmStream, data: bytes) -> None:
        await stream.sink.write(bytes(data))

    async def close(
        self,
        stream_id: str,
        *,
        failed: bool = False,
        stop_output: bool = True,
    ) -> None:
        stream = self._streams.get(stream_id)
        if stream is None:
            return
        async with self._operation_lock(stream.target_id):
            await self._close_unlocked(
                stream_id, failed=failed, stop_output=stop_output
            )

    async def _close_unlocked(
        self,
        stream_id: str,
        *,
        failed: bool = False,
        stop_output: bool = True,
    ) -> None:
        stream = self._streams.pop(stream_id, None)
        if stream is None:
            return
        try:
            if stop_output:
                await stream.sink.stop()
            else:
                await stream.sink.stop(stop_output=False)
        finally:
            await self.playback_service.session_coordinator.end(
                stream.session_id,
                failed=failed,
            )
            suite = self.playback_service.suite_registry.get(stream.target_id)
            if suite is not None and suite.current_session_id == stream.session_id:
                suite.current_session_id = None

    async def stop_target(self, target_id: str, *, stop_output: bool = True) -> None:
        normalized = normalize_target_id(target_id)
        async with self._operation_lock(normalized):
            await self._stop_target_unlocked(normalized, stop_output=stop_output)

    async def _stop_target_unlocked(
        self, target_id: str, *, stop_output: bool = True
    ) -> None:
        stream_ids = [
            stream_id
            for stream_id, stream in self._streams.items()
            if stream.target_id == target_id
        ]
        for stream_id in stream_ids:
            await self._close_unlocked(stream_id, stop_output=stop_output)

    async def close_all(self) -> None:
        for stream_id in list(self._streams):
            await self.close(stream_id)
