"""MiAir 主应用编排器"""

import asyncio
import logging
import os
import sys
import uuid

from aiohttp import web

from miair.auth import AuthManager
from miair.config import Config
from miair.dlna.device_server import DeviceServer
from miair.dlna.renderer import DLNARenderer
from miair.dlna.ssdp import SSDPServer
from miair.speaker import SpeakerManager
from miair.web.api import create_web_app
from miair.airplay.speaker_airplay import AirPlayManager
from miair.miplay.mdns import MiPlayIdentity
from miair.miplay.receiver import MiPlayReceiver
from miair.streaming.sink import MiAirLiveAudioSink

log = logging.getLogger("miair")


class MiAir:
    """MiAir 主应用"""

    AUTH_RETRY_DELAYS = (30, 120, 300, 900)

    def __init__(self, config: Config):
        self.config = config
        self.auth = AuthManager(config)
        self.speaker_manager = SpeakerManager(config, self.auth)
        self.renderers: dict[str, DLNARenderer] = {}  # udn -> DLNARenderer
        self._did_to_udn: dict[str, str] = {}  # did -> udn
        self.ssdp_server: SSDPServer | None = None
        self.device_server: DeviceServer | None = None
        self._web_runner: web.AppRunner | None = None
        self.dlna_running = False
        self.airplay_manager: AirPlayManager | None = None
        self.miplay_receiver: MiPlayReceiver | None = None
        self._auth_retry_task: asyncio.Task | None = None

    def get_renderer_by_did(self, did: str) -> DLNARenderer | None:
        """根据 DID 获取渲染器"""
        udn = self._did_to_udn.get(did)
        if udn:
            return self.renderers.get(udn)
        return None

    async def get_all_devices(self) -> list[dict]:
        """获取小米账号下所有设备列表"""
        if not self.config.account and not self.config.cookie:
            return []
        try:
            await self.auth.ensure_login()
            devices = await self.auth.get_device_list()
            return devices
        except Exception as e:
            log.warning(f"获取设备列表失败: {e}")
            return []

    async def _periodic_device_check(self):
        """定期检查设备；异常时启动进程内恢复而非重启进程。"""
        while True:
            await asyncio.sleep(60)
            
            # 如果没有开启自动重启，不执行此逻辑
            if not self.config.auto_restart:
                continue

            # 如果没有配置账号密码，不检查
            if not self.config.account and not self.config.cookie:
                continue
            
            try:
                devices = await self.get_all_devices()
                if not devices:
                    log.warning("定期检查未获取到设备，启动进程内认证恢复")
                    self._schedule_auth_retry()
            except Exception as e:
                log.warning(f"定期检查设备列表异常: {type(e).__name__}")
                self._schedule_auth_retry()

    def _schedule_auth_retry(self):
        """启动唯一的、带上限退避的认证/DLNA 恢复任务。"""
        if not self.config.auto_restart:
            return
        if self._auth_retry_task and not self._auth_retry_task.done():
            return
        self._auth_retry_task = asyncio.create_task(self._auth_retry_loop())

    async def _auth_retry_loop(self):
        attempt = 0
        try:
            while self.config.auto_restart:
                delay = self.AUTH_RETRY_DELAYS[
                    min(attempt, len(self.AUTH_RETRY_DELAYS) - 1)
                ]
                log.info(f"认证恢复将在 {delay} 秒后重试")
                await asyncio.sleep(delay)

                if not (self.config.account or self.config.cookie) or not self.config.mi_did:
                    return

                log.info(f"开始第 {attempt + 1} 次进程内认证恢复")
                await self.restart_dlna_services()
                if self.dlna_running:
                    log.info("进程内认证恢复成功")
                    return
                attempt += 1
        except asyncio.CancelledError:
            pass
        finally:
            if asyncio.current_task() is self._auth_retry_task:
                self._auth_retry_task = None

    async def start(self):
        """启动所有服务"""
        self._setup_logging()

        log.info("MiAir 启动中...")
        log.info(f"主机名: {self.config.hostname}")
        log.info(f"DLNA 端口: {self.config.dlna_port}")
        log.info(f"Web 端口: {self.config.web_port}")

        # 1. 先启动 Web 管理界面 (始终启动)
        web_app = create_web_app(self.config, self)
        self._web_runner = web.AppRunner(web_app, access_log=None)
        await self._web_runner.setup()
        web_site = web.TCPSite(self._web_runner, "0.0.0.0", self.config.web_port)
        await web_site.start()
        log.info(f"Web 管理界面: http://{self.config.hostname}:{self.config.web_port}")

        # 2. 如果已有账号和设备配置，启动 DLNA 和 AirPlay 服务
        if (self.config.account or self.config.cookie) and self.config.mi_did:
            await self._start_dlna_services()
        else:
            if not self.config.account and not self.config.cookie:
                log.info("未配置小米账号，请打开 Web 管理界面进行配置")
            elif not self.config.mi_did:
                log.info("未选择音箱设备，请打开 Web 管理界面选择设备")
            log.info(f"请访问 http://{self.config.hostname}:{self.config.web_port} 进行配置")

        self._device_check_task = asyncio.create_task(self._periodic_device_check())

    async def _start_dlna_services(self):
        """启动 DLNA 相关服务 (登录、初始化音箱、SSDP、HTTP)"""
        try:
            # 登录小米
            await self.auth.login()

            # 检查登录状态
            if not self.auth.is_logged_in():
                log.warning("登录失败，无法启动 DLNA 服务")
                # 清空渲染器和控制器，避免显示旧设备
                self.renderers.clear()
                self._did_to_udn.clear()
                if hasattr(self, 'speaker_manager'):
                    self.speaker_manager.controllers.clear()
                self._schedule_auth_retry()
                return

            # 获取设备列表，确保能正常获取新账号的设备
            device_list = await self.auth.get_device_list()
            if not device_list:
                log.warning("未获取到设备列表，无法启动 DLNA 服务")
                # 清空渲染器和控制器，避免显示旧设备
                self.renderers.clear()
                self._did_to_udn.clear()
                if hasattr(self, 'speaker_manager'):
                    self.speaker_manager.controllers.clear()

                self._schedule_auth_retry()
                return

            # 初始化音箱
            await self.speaker_manager.init_speakers()
            if not self.speaker_manager.controllers:
                log.warning("没有可用的音箱，请检查配置或重新选择设备")
                # 清空渲染器和控制器，避免显示旧设备
                self.renderers.clear()
                self._did_to_udn.clear()
                return

            # 为每个音箱创建 DLNA 渲染器
            self.ssdp_server = SSDPServer(self.config.hostname, self.config.dlna_port)
            self.device_server = DeviceServer(self.config.hostname, self.config.dlna_port, self.config)

            for did, controller in self.speaker_manager.controllers.items():
                speaker = controller.speaker
                udn = speaker.udn
                friendly_name = speaker.get_dlna_name()

                renderer = DLNARenderer(udn, friendly_name, controller, self.config.default_volume, config=self.config)
                self.renderers[udn] = renderer
                self._did_to_udn[did] = udn

                self.ssdp_server.register_renderer(udn, friendly_name)
                self.device_server.register_renderer(renderer)
                log.info(f"已创建渲染器: {friendly_name} (udn={udn})")

            # 启动 SSDP
            await self.ssdp_server.start()

            # 启动 DLNA HTTP 服务
            await self.device_server.start()

            self.dlna_running = True
            self.config.save()

            # 若服务通过手动配置更新恢复，取消尚未执行的后台重试；恢复
            # 任务自身会在看到 dlna_running=True 后自然结束。
            if (
                self._auth_retry_task
                and self._auth_retry_task is not asyncio.current_task()
                and not self._auth_retry_task.done()
            ):
                self._auth_retry_task.cancel()
                self._auth_retry_task = None

            # 启动 AirPlay 服务 - 每个音箱一个
            await self._start_airplay_for_speakers()
            await self._start_miplay_for_speaker()

            log.info(f"MiAir 服务启动完成! 共 {len(self.renderers)} 个音箱")
            log.info("手机 DLNA / AirPlay 现在应该能发现这些设备了")

        except Exception as e:
            log.error(f"启动 DLNA 服务失败: {e}")
            # 确保 dlna_running 为 False
            self.dlna_running = False
            # 清空渲染器和控制器，避免显示旧设备
            self.renderers.clear()
            self._did_to_udn.clear()
            if hasattr(self, 'speaker_manager'):
                self.speaker_manager.controllers.clear()
            self._schedule_auth_retry()

    async def _start_airplay_for_speakers(self):
        """为每个音箱启动独立的 AirPlay 接收服务"""
        try:
            if not self.speaker_manager.controllers:
                log.warning("没有可用的音箱，无法启动 AirPlay 服务")
                return

            self.airplay_manager = AirPlayManager(self.config.hostname, config=self.config)
            await self.airplay_manager.start_for_speakers(self.speaker_manager.controllers)
        except Exception as e:
            log.error(f"启动 AirPlay 服务失败: {e}")

    async def _start_miplay_for_speaker(self):
        """发布单个 MiPlay 网关，并把音频送到首个已配置音箱。"""
        if not self.config.enable_miplay:
            log.info("MiPlay 接收服务已禁用")
            return
        if self.miplay_receiver is not None or not self.speaker_manager.controllers:
            return
        did, controller = next(iter(self.speaker_manager.controllers.items()))
        speaker_name = controller.speaker.get_dlna_name()
        identity = MiPlayIdentity(
            address=self.config.hostname,
            friendly_name=f"{self.config.miplay_name} · {speaker_name}",
            instance=f"OpenXiaoCast-{uuid.uuid5(uuid.NAMESPACE_DNS, did).hex[:8]}",
            host=f"openxiaocast-{uuid.uuid5(uuid.NAMESPACE_DNS, did).hex[:8]}",
            device_id=uuid.uuid5(uuid.NAMESPACE_DNS, f"openxiaocast-miplay-{did}"),
            control_port=self.config.miplay_port,
        )
        receiver = MiPlayReceiver(
            host="0.0.0.0",
            port=self.config.miplay_port,
            sink_factory=lambda: MiAirLiveAudioSink(
                self.config.hostname,
                controller,
                play_type=self.config.miplay_play_type,
                http_mode=self.config.miplay_http_mode,
            ),
            volume_setter=controller.set_volume,
            identity=identity,
            advertise_address=self.config.hostname,
        )
        try:
            await receiver.start()
        except Exception as exc:
            log.error("启动 MiPlay 接收服务失败: %s", exc)
            await receiver.stop()
            return
        self.miplay_receiver = receiver
        log.info("MiPlay 网关已映射到音箱: %s", speaker_name)

    async def restart_dlna_services(self):
        """重启 DLNA 服务 (用户通过 Web 修改配置后调用)"""
        if self.airplay_manager:
            await self.airplay_manager.stop()
            self.airplay_manager = None
        # 先停止现有服务
        await self._stop_dlna_services()
        # 关闭并重新初始化 auth，确保账号切换生效
        await self.auth.close()
        self.auth = AuthManager(self.config)
        # 重建 speaker manager
        self.speaker_manager = SpeakerManager(self.config, self.auth)
        # 启动
        await self._start_dlna_services()

    async def _stop_dlna_services(self):
        """停止 DLNA 服务"""
        if self.miplay_receiver:
            await self.miplay_receiver.stop()
            self.miplay_receiver = None
        if self.ssdp_server:
            await self.ssdp_server.stop()
            self.ssdp_server = None
        if self.device_server:
            await self.device_server.stop()
            self.device_server = None
        self.renderers.clear()
        self._did_to_udn.clear()
        self.dlna_running = False

    async def stop(self):
        """停止所有服务"""
        log.info("MiAir 正在关闭...")

        if hasattr(self, '_device_check_task') and self._device_check_task:
            self._device_check_task.cancel()
        if self._auth_retry_task:
            self._auth_retry_task.cancel()
            self._auth_retry_task = None

        await self._stop_dlna_services()
        if self.airplay_manager:
            await self.airplay_manager.stop()
            self.airplay_manager = None
        if self._web_runner:
            # 添加超时，避免卡住
            try:
                await asyncio.wait_for(self._web_runner.cleanup(), timeout=3.0)
            except asyncio.TimeoutError:
                log.warning("Web 服务关闭超时")
        await self.auth.close()

        log.info("MiAir 已关闭")

    async def run_forever(self):
        """运行直到收到终止信号"""
        await self.start()
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def _setup_logging(self):
        """配置日志"""
        logger = logging.getLogger("miair")
        logger.setLevel(logging.DEBUG if self.config.verbose else logging.INFO)

        # 抑制 asyncio / aiohttp 内部的连接断开噪音日志
        logging.getLogger("asyncio").setLevel(logging.CRITICAL)
        logging.getLogger("aiohttp.server").setLevel(logging.WARNING)

        if logger.handlers:
            return

        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d: %(message)s",
            datefmt="[%Y-%m-%d %H:%M:%S]",
        )

        # 控制台 - Windows 下用 UTF-8 流避免 GBK 编码异常
        if sys.platform == "win32":
            import io
            stream = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace",
                line_buffering=True,
            )
            console = logging.StreamHandler(stream)
        else:
            console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

        # 文件 — 每次启动清空，大小上限 500KB（超过自动清空重写）
        if self.config.log_file:
            log_dir = os.path.dirname(self.config.log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            # 启动时清空旧日志
            try:
                open(self.config.log_file, "w", encoding="utf-8").close()
            except OSError:
                pass
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                self.config.log_file,
                maxBytes=500 * 1024,   # 500KB
                backupCount=0,         # 不保留备份，超限直接清空重写
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
