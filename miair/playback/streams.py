"""Fixed-format PCM input sessions backed by the existing live audio sink."""

from __future__ import annotations

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
        id_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ):
        self.playback_service = playback_service
        self.hostname = hostname
        self.sink_factory = sink_factory
        self.id_factory = id_factory
        self._streams: dict[str, PcmStream] = {}

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
        controller = self.playback_service.controller_for(normalized)
        await self.stop_target(normalized)
        session = await self.playback_service.session_coordinator.begin(
            normalized,
            IngressProtocol.MCP,
            media_format="PCM s16le 48 kHz · 2 ch",
        )
        suite = self.playback_service.suite_registry.get(normalized)
        suite.current_session_id = session.id
        sink = self.sink_factory(self.hostname, controller)
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

    async def close(self, stream_id: str, *, failed: bool = False) -> None:
        stream = self._streams.pop(stream_id, None)
        if stream is None:
            return
        try:
            await stream.sink.stop()
        finally:
            await self.playback_service.session_coordinator.end(
                stream.session_id,
                failed=failed,
            )
            suite = self.playback_service.suite_registry.get(stream.target_id)
            if suite is not None and suite.current_session_id == stream.session_id:
                suite.current_session_id = None

    async def stop_target(self, target_id: str) -> None:
        normalized = normalize_target_id(target_id)
        stream_ids = [
            stream_id
            for stream_id, stream in self._streams.items()
            if stream.target_id == normalized
        ]
        for stream_id in stream_ids:
            await self.close(stream_id)

    async def close_all(self) -> None:
        for stream_id in list(self._streams):
            await self.close(stream_id)
