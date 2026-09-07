"""每个音箱对应的 AirPlay 接收器

为每个小爱音箱创建一个独立的 AirPlay 接收服务，
手机连接后音频直接转发到对应音箱播放。
"""

import asyncio
import inspect
import logging
import time

from zeroconf import Zeroconf, IPVersion

from miair.airplay.server import AirPlayServer
from miair.speaker import SpeakerController

log = logging.getLogger("miair")


class SpeakerAirPlay:
    """单个音箱的 AirPlay 接收器包装"""

    def __init__(self, hostname: str, controller: SpeakerController,
                 shared_zeroconf: Zeroconf | None = None, config=None,
                 *, target_id: str | None = None, lifecycle_callback=None,
                 output_owner=None, operation_lock=None):
        self.hostname = hostname
        self.controller = controller
        self.speaker = controller.speaker
        target_name = self.speaker.get_dlna_name()
        self.device_name = (
            config.get_device_name(target_name) if config else target_name
        )
        self.shared_zeroconf = shared_zeroconf
        self.config = config
        self.target_id = target_id
        self.lifecycle_callback = lifecycle_callback
        self.output_owner = output_owner
        self.operation_lock = operation_lock
        self.airplay_server: AirPlayServer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None  # 保存事件循环引用
        # AirPlay 状态轮询（打断续播）
        self._stream_url: str = ""  # 当前播放的 HTTP 流 URL
        self._airplay_active: bool = False  # AirPlay 是否活跃
        self._poll_task: asyncio.Task | None = None  # 状态轮询任务
        self._play_grace_until: float = 0.0  # play 后宽限期
        self._session_id: str | None = None
        self._source_token = None
        self._route_lock = asyncio.Lock()

    def _physical_command_lock(self):
        if self.operation_lock is not None:
            return self.operation_lock()
        return self._route_lock

    async def _emit_lifecycle(self, event: str, details: dict | None = None):
        if self.lifecycle_callback is None:
            return None
        result = self.lifecycle_callback(event, dict(details or {}))
        if inspect.isawaitable(result):
            return await result
        return result

    async def _owns_output(self, session_id: str | None = None) -> bool:
        if self.output_owner is None:
            return True
        try:
            result = self.output_owner(session_id or self._session_id)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except asyncio.CancelledError:
            return False
        except Exception as exc:
            log.warning(
                "AirPlay 无法确认输出所有权，跳过音箱控制: %s",
                type(exc).__name__,
            )
            return False

    async def start(self):
        """启动该音箱的 AirPlay 服务"""
        try:
            # 保存当前事件循环，以便在 RTSP 线程中安全调用异步函数
            self._loop = asyncio.get_running_loop()

            self.airplay_server = AirPlayServer(
                self.hostname, self.device_name, self.shared_zeroconf,
                speaker_hardware=self.speaker.hardware
            )

            # 设置回调：直接播放到这个音箱
            self.airplay_server.on_play_start = self._on_play_start
            self.airplay_server.on_play_stop = self._on_play_stop
            self.airplay_server.on_volume_change = self._on_volume_change

            await self.airplay_server.start()
            log.info(f"音箱 {self.device_name} 的 AirPlay 服务已启动，端口: {self.airplay_server.rtsp_port}")
        except Exception as e:
            log.error(f"启动音箱 {self.device_name} 的 AirPlay 服务失败: {e}")
            raise

    async def stop(self):
        """停止该音箱的 AirPlay 服务"""
        if self._airplay_active or self._session_id is not None:
            await self._stop_speaker()
        if self.airplay_server:
            await self.airplay_server.stop()
            self.airplay_server = None
            log.info(f"音箱 {self.device_name} 的 AirPlay 服务已停止")

    def _on_play_start(self, stream_url: str, source_token=None):
        """AirPlay 开始播放 - 直接推送到这个音箱

        注意: 这个回调从 RTSP 线程调用，不在 asyncio 事件循环中。
        必须使用 run_coroutine_threadsafe 安全调度异步任务。
        """
        log.info(f"AirPlay 音频推送到 {self.device_name}: {stream_url}")
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._play_on_speaker(stream_url, source_token), self._loop
            )
        else:
            log.warning(f"AirPlay: 事件循环未运行，无法播放到 {self.device_name}")

    async def _play_on_speaker(self, stream_url: str, source_token=None):
        """在对应音箱上播放"""
        async with self._physical_command_lock():
            session_id = None
            try:
                session_id = await self._emit_lifecycle(
                    "session_started", {"media_format": "AirPlay PCM"}
                )
                self._session_id = session_id
                self._source_token = source_token
                self._stream_url = stream_url
                self._airplay_active = True
                self._play_grace_until = time.time() + 10.0  # 10秒宽限期
                success = await self.controller.play_url(stream_url)
                if success:
                    await self._emit_lifecycle(
                        "media_started", {"session_id": session_id}
                    )
                    log.info(f"AirPlay 音频已在 {self.device_name} 开始播放: {stream_url}")
                    self._start_poll()
                    if self.config:
                        default_vol = getattr(self.config, 'default_volume', 0)
                        follow_dev_vol = getattr(self.config, 'follow_device_volume', False)
                        if follow_dev_vol:
                            try:
                                current_vol = await self.controller.get_volume()
                                if self.airplay_server:
                                    self.airplay_server._last_volume_db = self._vol_pct_to_db(current_vol)
                                log.info(f"AirPlay 已跟随设备当前音量到 {self.device_name}: {current_vol}%")
                            except Exception as e:
                                log.error(f"AirPlay 获取当前音量失败: {e}")
                        elif default_vol > 0:
                            await asyncio.sleep(0.5)
                            if await self._owns_output(session_id):
                                await self.controller.set_volume(default_vol)
                            if self.airplay_server:
                                self.airplay_server._last_volume_db = self._vol_pct_to_db(default_vol)
                            log.info(f"AirPlay 已应用默认音量到 {self.device_name}: {default_vol}%")
                else:
                    await self._emit_lifecycle(
                        "session_ended",
                        {
                            "session_id": session_id,
                            "failed": True,
                            "error_code": "OUTPUT_PLAY_URL_REJECTED",
                        },
                    )
                    self._airplay_active = False
                    self._stream_url = ""
                    self._session_id = None
                    log.warning(f"AirPlay 音频在 {self.device_name} 播放失败")
            except Exception as e:
                await self._emit_lifecycle(
                    "session_ended",
                    {
                        "session_id": session_id,
                        "failed": True,
                        "error_code": "OUTPUT_PLAY_URL_FAILED",
                    },
                )
                self._airplay_active = False
                self._stream_url = ""
                self._session_id = None
                log.error(f"AirPlay 播放到 {self.device_name} 失败: {e}")

    @staticmethod
    def _vol_pct_to_db(volume: int) -> float:
        """音箱百分比 → AirPlay dB 值（线性映射逆运算）

        iOS 步骤 1-16 线性映射: -28.125 dB ~ 0 dB → 音箱 6% ~ 100%
        逆向: dB = (volume - 6) / 94 * 28.125 - 28.125
        """
        import math
        if volume <= 0:
            return -144.0
        if volume >= 100:
            return 0.0
        if volume <= 6:
            return -28.125
        return (volume - 6) / 94.0 * 28.125 - 28.125

    def _on_play_stop(self, source_token=None):
        """AirPlay 停止播放

        注意: 这个回调从 RTSP 线程调用，不在 asyncio 事件循环中。
        """
        log.info(f"AirPlay 停止播放到 {self.device_name}")
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._stop_speaker(source_token), self._loop
            )
        else:
            log.warning(f"AirPlay: 事件循环未运行，无法停止 {self.device_name}")

    async def _stop_speaker(self, source_token=None):
        """停止音箱播放"""
        if source_token is not None and source_token is not self._source_token:
            return
        self._source_token = None
        session_id = self._session_id
        self._session_id = None
        self._airplay_active = False
        self._stream_url = ""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        async with self._physical_command_lock():
            if await self._owns_output(session_id):
                try:
                    await self.controller.stop()
                except Exception:
                    pass
            await self._emit_lifecycle(
                "session_ended", {"session_id": session_id, "failed": False}
            )

    def _start_poll(self):
        """启动 AirPlay 状态轮询任务（仅在 auto_resume_on_interrupt 开启时）"""
        # 未开启自动续播则不启动轮询，避免无意义的 API 调用
        if self.config and not getattr(self.config, 'auto_resume_on_interrupt', False):
            return
        if self._poll_task and not self._poll_task.done():
            return  # 已在运行
        self._poll_task = asyncio.create_task(self._poll_speaker_state())

    async def _poll_speaker_state(self):
        """轮询音箱状态，检测打断并自动续播

        当音箱被语音唤醒打断（status 从 playing 变成 stopped）时，
        只要 AirPlay 音频流仍然活跃，就自动重新 play_url 恢复播放。
        """
        try:
            while self._airplay_active and self._stream_url:
                await asyncio.sleep(3)  # 3秒轮询一次
                if not self._airplay_active or not self._stream_url:
                    break

                # 检查 AirPlay 音频流是否还在输出
                if self.airplay_server and not self.airplay_server.is_playing:
                    break

                # 宽限期内不轮询
                if time.time() < self._play_grace_until:
                    continue

                try:
                    status = await asyncio.wait_for(
                        self.controller.get_status(), timeout=10
                    )
                    speaker_status = status.get("status", 0)
                    # status: 0=stopped, 1=playing, 2=paused
                    if speaker_status == 1:
                        continue  # 正在播放，一切正常

                    # 音箱不在播放状态，但 AirPlay 流还在 → 被打断了
                    log.info(
                        f"[{self.device_name}] AirPlay 检测到播放中断 "
                        f"(speaker_status={speaker_status})，"
                        f"等待后自动续播..."
                    )
                    # 等待打断结束（如语音回复完毕）
                    resume_delay = 5
                    if self.config:
                        resume_delay = getattr(self.config, 'resume_delay_seconds', 5)
                    await asyncio.sleep(resume_delay)

                    # 再次检查 AirPlay 是否仍然活跃
                    if not self._airplay_active or not self._stream_url:
                        break
                    if self.airplay_server and not self.airplay_server.is_playing:
                        break
                    if not await self._owns_output():
                        self._airplay_active = False
                        break

                    # 重新播放（使用新 URL 防止音箱缓存旧响应）
                    base_url = self._stream_url.split('?')[0]
                    fresh_url = f"{base_url}?sid={int(time.time())}"
                    log.info(f"[{self.device_name}] AirPlay 自动续播: {fresh_url}")
                    self._play_grace_until = time.time() + 10.0
                    async with self._physical_command_lock():
                        if not await self._owns_output():
                            self._airplay_active = False
                            break
                        success = await self.controller.play_url(fresh_url)
                    if success:
                        log.info(f"[{self.device_name}] AirPlay 续播成功")
                    else:
                        log.warning(f"[{self.device_name}] AirPlay 续播失败")

                except Exception as e:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            pass

    def _on_volume_change(self, vol_db: float, source_token=None):
        """处理音量改变

        注意: 这个回调从 RTSP 线程调用，不在 asyncio 事件循环中。

        iOS 步骤 1-16 线性映射 dB → 音箱百分比:
          步骤 0 (静音) → 0%
          步骤 1 (-28.125 dB) → 6%
          步骤 8 (-15.0 dB)  → 50%
          步骤 16 (0 dB)     → 100%
        """
        if vol_db <= -144:
            volume = 0
        elif vol_db >= 0:
            volume = 100
        else:
            # 线性映射: -28.125 dB ~ 0 dB → 6% ~ 100%
            volume = int(6 + (vol_db + 28.125) / 28.125 * 94)
            volume = max(0, min(100, volume))
            if volume == 0 and vol_db > -144:
                volume = 1

        log.info(f"AirPlay 音量同步到 {self.device_name}: {vol_db} dB -> {volume}%")
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._set_volume(volume, source_token), self._loop
            )

    async def _set_volume(self, volume: int, source_token=None) -> None:
        if source_token is not None and source_token is not self._source_token:
            return
        async with self._physical_command_lock():
            if await self._owns_output():
                await self.controller.set_volume(volume)


class AirPlayManager:
    """管理所有音箱的 AirPlay 接收器"""

    def __init__(self, hostname: str, config=None, *, lifecycle_callback=None,
                 output_owner=None, operation_lock=None):
        self.hostname = hostname
        self.config = config
        self.lifecycle_callback = lifecycle_callback
        self.output_owner = output_owner
        self.operation_lock = operation_lock
        self.speaker_airplays: dict[str, SpeakerAirPlay] = {}  # did -> SpeakerAirPlay
        self._shared_zeroconf: Zeroconf | None = None

    async def start_for_speakers(self, controllers: dict[str, SpeakerController]):
        """为所有音箱启动 AirPlay 服务"""
        # 创建一个共享的 Zeroconf 实例
        if not self._shared_zeroconf:
            self._shared_zeroconf = Zeroconf(
                interfaces=[self.hostname],
                ip_version=IPVersion.V4Only,
            )
            log.info("创建共享 Zeroconf 实例用于所有音箱，接口: %s", self.hostname)

        for did, controller in controllers.items():
            if did in self.speaker_airplays:
                # 已经存在，跳过
                continue

            try:
                await self.start_for_speaker(did, controller)
            except Exception as e:
                log.error(f"为音箱 {controller.speaker.get_dlna_name()} 启动 AirPlay 失败: {e}")

        log.info(f"共启动了 {len(self.speaker_airplays)} 个音箱的 AirPlay 服务")

    async def start_for_speaker(
        self,
        did: str,
        controller: SpeakerController,
    ) -> SpeakerAirPlay:
        """Start and return one independently managed AirPlay receiver."""
        existing = self.speaker_airplays.get(did)
        if existing is not None:
            return existing
        if not self._shared_zeroconf:
            self._shared_zeroconf = Zeroconf(
                interfaces=[self.hostname],
                ip_version=IPVersion.V4Only,
            )
            log.info("创建共享 Zeroconf 实例用于所有音箱，接口: %s", self.hostname)
        speaker_airplay = SpeakerAirPlay(
            self.hostname,
            controller,
            self._shared_zeroconf,
            config=self.config,
            target_id=getattr(controller, "target_id", did),
            lifecycle_callback=(
                lambda event, details: self.lifecycle_callback(
                    getattr(controller, "target_id", did), event, details
                )
                if self.lifecycle_callback is not None
                else None
            ),
            output_owner=(
                lambda session_id: self.output_owner(
                    getattr(controller, "target_id", did), session_id
                )
                if self.output_owner is not None
                else None
            ),
            operation_lock=(
                lambda: self.operation_lock(getattr(controller, "target_id", did))
                if self.operation_lock is not None
                else None
            ),
        )
        await speaker_airplay.start()
        self.speaker_airplays[did] = speaker_airplay
        return speaker_airplay

    async def stop(self):
        """停止所有 AirPlay 服务"""
        for did, speaker_airplay in list(self.speaker_airplays.items()):
            try:
                await speaker_airplay.stop()
            except Exception as e:
                log.error(f"停止音箱 AirPlay 失败: {e}")
        self.speaker_airplays.clear()

        # 关闭共享的 zeroconf
        if self._shared_zeroconf:
            try:
                await asyncio.to_thread(self._shared_zeroconf.close)
                log.info("共享 Zeroconf 已关闭")
            except Exception as e:
                log.error(f"关闭 Zeroconf 失败: {e}")
            self._shared_zeroconf = None

        log.info("所有 AirPlay 服务已停止")

    async def stop_for_speaker(self, did: str) -> SpeakerAirPlay | None:
        """Stop one receiver while keeping the shared Zeroconf instance alive."""
        speaker_airplay = self.speaker_airplays.get(did)
        if speaker_airplay is None:
            return None
        await speaker_airplay.stop()
        del self.speaker_airplays[did]
        log.info("已停止单个音箱的 AirPlay 服务: %s", did)
        return speaker_airplay

    async def restart_for_speakers(self, controllers: dict[str, SpeakerController]):
        """重新为音箱启动 AirPlay 服务"""
        await self.stop()
        await self.start_for_speakers(controllers)
