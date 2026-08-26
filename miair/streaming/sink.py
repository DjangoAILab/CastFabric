"""PCM sink that asks a configured Xiaomi speaker to pull a live HTTP stream."""

from __future__ import annotations

import logging
import time

from miair.airplay.audio_stream import AudioStreamServer


log = logging.getLogger("miair")


class MiAirLiveAudioSink:
    def __init__(
        self,
        hostname: str,
        controller,
        audio_format: str = "wav",
        play_type: int = 2,
        http_mode: str = "close",
        content_type: str = "audio/wav",
    ):
        self.hostname = hostname
        self.controller = controller
        self.audio_format = audio_format
        self.play_type = play_type
        self.http_mode = http_mode
        self.content_type = content_type
        self.stream_server: AudioStreamServer | None = None
        self._play_started = False
        self._active = False
        self._pcm_bytes = 0
        self._started_at: float | None = None
        self._first_pcm_at: float | None = None

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
        try:
            await server.start()
            server.set_audio_params(sample_rate, channels, sample_width)
            server.start_streaming()
            self._active = True
            accepted = await self.controller.play_url(
                server.stream_url, play_type=self.play_type
            )
            if not accepted:
                raise RuntimeError("Xiaomi speaker rejected the MiPlay live URL")
            self._play_started = True
            log.info(
                "MiPlay 音频已请求音箱拉流: %s "
                "(player_play_url type=%s, HTTP=%s, Content-Type=%s)",
                server.stream_url,
                self.play_type,
                self.http_mode,
                self.content_type,
            )
        except Exception:
            self._active = False
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
        self._pcm_bytes += len(payload)
        self.stream_server.write_pcm(payload)

    async def stop(self) -> None:
        server = self.stream_server
        self._active = False
        if server is not None:
            server.stop_streaming()
            await server.stop()
            self.stream_server = None
        if self._play_started:
            self._play_started = False
            try:
                await self.controller.stop()
            except Exception as exc:
                log.debug("停止 MiPlay 音箱播放失败: %s", exc)

    def diagnostics(self) -> dict:
        return {
            "active": self._active,
            "play_started": self._play_started,
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
