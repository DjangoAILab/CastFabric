"""PCM sink that asks a configured Xiaomi speaker to pull a live HTTP stream."""

from __future__ import annotations

import logging

from miair.airplay.audio_stream import AudioStreamServer


log = logging.getLogger("miair")


class MiAirLiveAudioSink:
    def __init__(self, hostname: str, controller, audio_format: str = "wav"):
        self.hostname = hostname
        self.controller = controller
        self.audio_format = audio_format
        self.stream_server: AudioStreamServer | None = None
        self._play_started = False
        self._active = False
        self._pcm_bytes = 0

    async def start(
        self, sample_rate: int, channels: int, sample_width: int
    ) -> None:
        if self._active:
            raise RuntimeError("live audio sink is already active")
        server = AudioStreamServer(
            self.hostname,
            0,
            audio_format=self.audio_format,
            stream_path="/miplay",
            source_name="MiPlay",
        )
        self.stream_server = server
        try:
            await server.start()
            server.set_audio_params(sample_rate, channels, sample_width)
            server.start_streaming()
            self._active = True
            accepted = await self.controller.play_url(server.stream_url)
            if not accepted:
                raise RuntimeError("Xiaomi speaker rejected the MiPlay live URL")
            self._play_started = True
            log.info("MiPlay 音频已请求音箱拉流: %s", server.stream_url)
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
            "stream_url": self.stream_server.stream_url
            if self.stream_server
            else None,
        }
