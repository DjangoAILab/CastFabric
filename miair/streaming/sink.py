"""PCM sink that asks a configured Xiaomi speaker to pull a live HTTP stream."""

from __future__ import annotations

import asyncio
import logging
import inspect
import time
from collections.abc import Awaitable, Callable

from miair.airplay.audio_stream import AudioStreamServer


log = logging.getLogger("miair")


class CastFabricLiveAudioSink:
    def __init__(
        self,
        hostname: str,
        controller,
        audio_format: str = "wav",
        play_type: int = 2,
        http_mode: str = "close",
        content_type: str = "audio/wav",
        output_pull_timeout: float = 5.0,
        lifecycle_callback: Callable[[str, dict], Awaitable[object] | object]
        | None = None,
        output_owner: Callable[[], Awaitable[bool] | bool] | None = None,
        operation_lock: Callable[[], object] | None = None,
    ):
        self.hostname = hostname
        self.controller = controller
        self.audio_format = audio_format
        self.play_type = play_type
        self.http_mode = http_mode
        self.content_type = content_type
        self.output_pull_timeout = max(0.05, float(output_pull_timeout))
        self.lifecycle_callback = lifecycle_callback
        self.output_owner = output_owner
        self.operation_lock = operation_lock
        self.stream_server: AudioStreamServer | None = None
        self._play_started = False
        self._pull_confirmed = False
        self._active = False
        self._pcm_bytes = 0
        self._started_at: float | None = None
        self._first_pcm_at: float | None = None
        self._route_lock = asyncio.Lock()

    def _physical_command_lock(self):
        if self.operation_lock is not None:
            return self.operation_lock()
        return self._route_lock

    async def _emit_lifecycle(self, event: str, details: dict | None = None) -> None:
        if self.lifecycle_callback is None:
            return
        try:
            result = self.lifecycle_callback(event, dict(details or {}))
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            return
        except Exception as exc:
            # The output stream is the product path; diagnostics are best-effort.
            log.debug("MiPlay 输出生命周期回调失败 (%s): %s", event, type(exc).__name__)

    async def _owns_output(self) -> bool:
        """Return whether this sink may still mutate the physical renderer."""
        if self.output_owner is None:
            return True
        try:
            result = self.output_owner()
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except asyncio.CancelledError:
            return False
        except Exception as exc:
            # Ownership cannot be proven, so a stale cleanup must fail closed.
            log.warning("无法确认实时流输出所有权，跳过音箱控制: %s", type(exc).__name__)
            return False

    async def _stop_output_if_owned(self) -> None:
        async with self._physical_command_lock():
            if not await self._owns_output():
                return
            try:
                await self.controller.stop()
            except Exception as exc:
                log.debug("停止实时流音箱播放失败: %s", type(exc).__name__)

    async def start(
        self, sample_rate: int, channels: int, sample_width: int
    ) -> None:
        if self._active:
            raise RuntimeError("live audio sink is already active")
        self._started_at = time.monotonic()
        server = AudioStreamServer(
            self.hostname,
            0,
            audio_format=self.audio_format,
            stream_path="/miplay",
            source_name="MiPlay",
            close_delimited=True,
            wav_http_mode=self.http_mode,
            wav_content_type=self.content_type,
            queue_maxsize=8,
        )
        self.stream_server = server
        failure_reason = "OUTPUT_STREAM_START_FAILED"
        try:
            await server.start()
            server.set_audio_params(sample_rate, channels, sample_width)
            server.start_streaming()
            self._active = True
            async with self._physical_command_lock():
                if not await self._owns_output():
                    failure_reason = "OUTPUT_OWNERSHIP_LOST"
                    raise RuntimeError("live audio session no longer owns the output")
                accepted = await self.controller.play_url(
                    server.stream_url, play_type=self.play_type
                )
            if not accepted:
                failure_reason = "OUTPUT_PLAY_URL_REJECTED"
                raise RuntimeError("Xiaomi speaker rejected the MiPlay live URL")
            self._play_started = True
            failure_reason = "OUTPUT_PULL_TIMEOUT"
            if not await server.wait_for_client(self.output_pull_timeout):
                raise RuntimeError(
                    "physical renderer accepted playback but did not pull "
                    "the MiPlay live URL"
                )
            if not await self._owns_output():
                failure_reason = "OUTPUT_OWNERSHIP_LOST"
                raise RuntimeError("live audio session lost output ownership")
            self._pull_confirmed = True
            await self._emit_lifecycle(
                "output_started",
                {
                    "output_adapter": type(self.controller).__name__,
                    "media_format": self.audio_format,
                },
            )
            log.info(
                "MiPlay 音频已请求音箱拉流: %s "
                "(player_play_url type=%s, HTTP=%s, Content-Type=%s)",
                server.stream_url,
                self.play_type,
                self.http_mode,
                self.content_type,
            )
        except Exception:
            await self._emit_lifecycle(
                "output_failed",
                {"reason": failure_reason},
            )
            self._active = False
            if self._play_started:
                await self._stop_output_if_owned()
                self._play_started = False
            server.stop_streaming()
            await server.stop()
            self.stream_server = None
            raise

    async def write(self, data: bytes) -> None:
        if not self._active or self.stream_server is None:
            raise RuntimeError("live audio sink is not active")
        payload = bytes(data)
        if self._first_pcm_at is None:
            self._first_pcm_at = time.monotonic()
            elapsed_ms = (
                (self._first_pcm_at - self._started_at) * 1000
                if self._started_at is not None
                else 0
            )
            log.info("MiPlay 首个 PCM 已送入音箱拉流: 启动后 %.0fms", elapsed_ms)
            await self._emit_lifecycle(
                "pcm_forwarded",
                {"media_format": self.audio_format},
            )
        self._pcm_bytes += len(payload)
        self.stream_server.write_pcm(payload)

    async def stop(self, *, stop_output: bool = True) -> None:
        server = self.stream_server
        self._active = False
        if server is not None:
            server.stop_streaming()
            await server.stop()
            self.stream_server = None
        if self._play_started:
            self._play_started = False
            if stop_output:
                await self._stop_output_if_owned()
        self._pull_confirmed = False
        await self._emit_lifecycle("output_stopped")

    def diagnostics(self) -> dict:
        return {
            "active": self._active,
            "play_started": self._play_started,
            "pull_confirmed": self._pull_confirmed,
            "pcm_bytes": self._pcm_bytes,
            "first_pcm_ms": round(
                (self._first_pcm_at - self._started_at) * 1000
            )
            if self._first_pcm_at is not None and self._started_at is not None
            else None,
            "stream_url": self.stream_server.stream_url
            if self.stream_server
            else None,
        }


# Compatibility alias for the original internal integration name.
MiAirLiveAudioSink = CastFabricLiveAudioSink
