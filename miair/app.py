"""CastFabric 主应用编排器。"""

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

from aiohttp import web

from miair.auth import AuthManager
from miair.config import Config
from miair.dlna.device_server import DeviceServer
from miair.dlna.client import LocalDLNAClient
from miair.dlna.renderer import DLNARenderer
from miair.dlna.ssdp import SSDPServer
from miair.speaker import SpeakerManager
from miair.web.api import create_web_app
from miair.airplay.speaker_airplay import AirPlayManager
from miair.miplay.mdns import MiPlayIdentity
from miair.miplay.receiver import MiPlayReceiver
from miair.streaming.sink import CastFabricLiveAudioSink
from miair.identity import PRODUCT_NAME, PRODUCT_SLUG
from miair.runtime.events import ActivityEventJournal
from miair.runtime.discovery import TargetDiscoveryRegistry
from miair.runtime.models import (
    EventOutcome,
    IngressProtocol,
    IngressState,
    SessionState,
)
from miair.runtime.sessions import MediaSessionCoordinator
from miair.runtime.suites import ReceiverSuite, ReceiverSuiteRegistry

log = logging.getLogger("miair")


class CastFabric:
    """CastFabric 主应用；旧导入名在文件末尾保留兼容别名。"""

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
        self.miplay_receivers: dict[str, MiPlayReceiver] = {}
        self.activity_journal = ActivityEventJournal(
            path=os.path.join(self.config.conf_path, "activity.jsonl")
        )
        self.session_coordinator = MediaSessionCoordinator(
            journal=self.activity_journal
        )
        self._miplay_session_ids: dict[str, str] = {}
        self.discovered_targets = {}
        self._auth_retry_task: asyncio.Task | None = None
        self.suite_registry = ReceiverSuiteRegistry(
            device_name_prefix=self.config.device_name_prefix
        )
        self.discovery_registry = TargetDiscoveryRegistry(
            self._discover_output_targets
        )

    @property
    def miplay_receiver(self) -> MiPlayReceiver | None:
        """First receiver compatibility view for the migration release."""
        if not self.miplay_receivers:
            return None
        return self.miplay_receivers[sorted(self.miplay_receivers)[0]]

    def get_renderer_by_did(self, did: str) -> DLNARenderer | None:
        """根据 DID 获取渲染器"""
        udn = self._did_to_udn.get(did)
        if udn:
            return self.renderers.get(udn)
        return None

    def has_local_speaker_control(self) -> bool:
        """是否至少有一个实体音箱可通过本地 DLNA 直接控制。"""
        return any(
            controller.local_dlna is not None
            for controller in self.speaker_manager.controllers.values()
        )

    async def _discover_output_targets(self):
        observed = await LocalDLNAClient.discover(self.config.hostname)
        virtual_ids = {f"uuid:{renderer.udn}" for renderer in self.renderers.values()}
        return [target for target in observed if target.id not in virtual_ids]

    async def get_all_devices(self) -> list[dict]:
        """获取小米账号下所有设备列表"""
        if not self.config.enable_xiaomi_extension:
            return []
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

            if not self.config.enable_xiaomi_extension:
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
        if not self.config.enable_xiaomi_extension:
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
                if await self.auth.login():
                    await self.auth.update_speakers_info()
                    self.config.save()
                    if not self.dlna_running:
                        await self._start_dlna_services()
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

        log.info("%s 启动中...", PRODUCT_NAME)
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

        # 2. 已选择过设备就可从本地缓存发布局域网投送入口；小米云
        # 认证只决定播放控制是否可用，不再决定设备能否被发现。
        if self.config.get_enabled_targets():
            await self._start_dlna_services()
        else:
            log.info("未选择 DLNA 输出目标，请打开 Web 管理界面扫描并选择设备")
            if self.config.account or self.config.cookie:
                log.info("已检测到旧小米云配置，将作为可选兼容扩展保留")
            log.info(f"请访问 http://{self.config.hostname}:{self.config.web_port} 进行配置")

        self._device_check_task = asyncio.create_task(self._periodic_device_check())

    async def _start_dlna_services(self):
        """启动 DLNA 相关服务 (登录、初始化音箱、SSDP、HTTP)"""
        try:
            has_xiaomi_config = bool(
                self.config.enable_xiaomi_extension
                and (self.config.account or self.config.cookie)
            )
            cloud_authenticated = False
            if has_xiaomi_config:
                cloud_authenticated = bool(await self.auth.login())
            if has_xiaomi_config and not cloud_authenticated:
                log.warning(
                    "小米云认证不可用；继续发布已缓存的局域网投送设备，"
                    "并尝试发现实体音箱的本地 DLNA 控制通道"
                )
                self._schedule_auth_retry()
            elif not has_xiaomi_config:
                log.info("未启用小米云扩展；使用标准局域网输出目标")

            # 初始化音箱
            await self.speaker_manager.init_speakers(
                refresh_from_cloud=cloud_authenticated
            )
            if cloud_authenticated and not self.auth.is_logged_in():
                cloud_authenticated = False
                log.warning(
                    "持久化的小米服务凭据已被云端拒绝；"
                    "保留局域网投送设备并进入认证恢复"
                )
                self._schedule_auth_retry()
            if not self.speaker_manager.controllers:
                log.warning("没有可用的音箱，请检查配置或重新选择设备")
                # 清空渲染器和控制器，避免显示旧设备
                self.renderers.clear()
                self._did_to_udn.clear()
                return

            if (
                has_xiaomi_config
                and not cloud_authenticated
                and self.has_local_speaker_control()
            ):
                log.info("小米云认证不可用，但实体音箱本地 DLNA 控制已就绪")

            # 为每个音箱创建 DLNA 渲染器
            self.ssdp_server = SSDPServer(self.config.hostname, self.config.dlna_port)
            self.device_server = DeviceServer(self.config.hostname, self.config.dlna_port, self.config)
            self.suite_registry.clear()

            for did, controller in self.speaker_manager.controllers.items():
                target = self.config.get_target(controller.target_id)
                if target is None:
                    log.error("控制器缺少输出目标配置: %s", controller.target_id)
                    continue
                suite = self.suite_registry.register(target, did, controller)
                try:
                    await self._register_dlna_renderer(suite)
                except Exception as exc:
                    log.error("为输出目标 %s 创建 DLNA 入口失败: %s", target.id, exc)
                    self.suite_registry.set_ingress(
                        target.id,
                        IngressProtocol.DLNA,
                        IngressState.UNAVAILABLE,
                        error_code="DLNA_START_FAILED",
                    )

            # 启动 SSDP
            await self.ssdp_server.start()

            # 启动 DLNA HTTP 服务
            await self.device_server.start()

            self.dlna_running = True
            self.config.save()

            # 若服务通过手动配置更新恢复，取消尚未执行的后台重试；恢复
            # 任务自身会在看到 dlna_running=True 后自然结束。
            if (
                self.auth.is_logged_in()
                and self._auth_retry_task
                and self._auth_retry_task is not asyncio.current_task()
                and not self._auth_retry_task.done()
            ):
                self._auth_retry_task.cancel()
                self._auth_retry_task = None

            # 启动 AirPlay 服务 - 每个音箱一个
            await self._start_airplay_for_speakers()
            await self._start_miplay_for_speakers()

            log.info(
                "%s 服务启动完成! 共 %s 个输出目标",
                PRODUCT_NAME,
                len(self.renderers),
            )
            log.info("手机 DLNA / AirPlay 现在应该能发现这些设备了")

        except Exception as e:
            log.error(f"启动 DLNA 服务失败: {e}")
            # 确保 dlna_running 为 False
            self.dlna_running = False
            # 清空渲染器和控制器，避免显示旧设备
            self.renderers.clear()
            self._did_to_udn.clear()
            self.suite_registry.clear()
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
            for did, controller in self.speaker_manager.controllers.items():
                wrapper = self.airplay_manager.speaker_airplays.get(did)
                if wrapper is None:
                    self.suite_registry.set_ingress(
                        controller.target_id,
                        IngressProtocol.AIRPLAY,
                        IngressState.UNAVAILABLE,
                        error_code="AIRPLAY_START_FAILED",
                    )
                    continue
                server = wrapper.airplay_server
                self.suite_registry.set_ingress(
                    controller.target_id,
                    IngressProtocol.AIRPLAY,
                    IngressState.READY,
                    handle=wrapper,
                    port=server.rtsp_port if server else None,
                )
        except Exception as e:
            log.error(f"启动 AirPlay 服务失败: {e}")
            for suite_snapshot in self.suite_registry.snapshots():
                self.suite_registry.set_ingress(
                    suite_snapshot.target.id,
                    IngressProtocol.AIRPLAY,
                    IngressState.UNAVAILABLE,
                    error_code="AIRPLAY_START_FAILED",
                )

    async def _register_dlna_renderer(self, suite: ReceiverSuite) -> DLNARenderer:
        """Register one virtual renderer on the process-wide DLNA servers."""
        if self.ssdp_server is None or self.device_server is None:
            raise RuntimeError("shared DLNA servers are not initialized")
        speaker = suite.controller.speaker
        renderer = DLNARenderer(
            speaker.udn,
            suite.target.get_receiver_alias(self.config.device_name_prefix),
            suite.controller,
            self.config.default_volume,
            config=self.config,
        )
        try:
            self.renderers[renderer.udn] = renderer
            self._did_to_udn[suite.controller_id] = renderer.udn
            self.ssdp_server.register_renderer(renderer.udn, renderer.friendly_name)
            self.device_server.register_renderer(renderer)
            self.suite_registry.set_ingress(
                suite.target.id,
                IngressProtocol.DLNA,
                IngressState.READY,
                handle=renderer,
                port=self.config.dlna_port,
            )
        except Exception:
            self.renderers.pop(renderer.udn, None)
            self._did_to_udn.pop(suite.controller_id, None)
            if renderer.udn in self.device_server.renderers:
                await self.device_server.unregister_renderer(renderer.udn)
            if renderer.udn in self.ssdp_server.renderers:
                await self.ssdp_server.unregister_renderer(renderer.udn)
            raise
        log.info("已创建渲染器: %s (udn=%s)", renderer.friendly_name, renderer.udn)
        return renderer

    async def _start_receiver_suite(self, suite: ReceiverSuite) -> None:
        dlna_runtime = suite.get_ingress(IngressProtocol.DLNA)
        renderer = dlna_runtime.handle if dlna_runtime else None
        renderer_is_live = bool(
            renderer is not None
            and renderer.udn in self.renderers
            and self.ssdp_server
            and renderer.udn in self.ssdp_server.renderers
            and self.device_server
            and renderer.udn in self.device_server.renderers
        )
        if not renderer_is_live:
            renderer = await self._register_dlna_renderer(suite)
            if self.ssdp_server:
                await self.ssdp_server.announce_renderer(renderer.udn)
        if self.airplay_manager is None:
            self.airplay_manager = AirPlayManager(self.config.hostname, config=self.config)
        try:
            wrapper = await self.airplay_manager.start_for_speaker(
                suite.controller_id,
                suite.controller,
            )
        except Exception:
            self.suite_registry.set_ingress(
                suite.target.id,
                IngressProtocol.AIRPLAY,
                IngressState.UNAVAILABLE,
                error_code="AIRPLAY_START_FAILED",
            )
        else:
            server = wrapper.airplay_server
            self.suite_registry.set_ingress(
                suite.target.id,
                IngressProtocol.AIRPLAY,
                IngressState.READY,
                handle=wrapper,
                port=server.rtsp_port if server else None,
            )
        if self.config.enable_miplay and suite.target.id not in self.miplay_receivers:
            port = self._miplay_port_for_target(suite.target.id)
            await self._start_miplay_for_target(suite, port)

    async def _stop_receiver_suite(self, suite: ReceiverSuite) -> None:
        miplay = self.miplay_receivers.pop(suite.target.id, None)
        if miplay is not None:
            await miplay.stop()
        miplay_runtime = suite.get_ingress(IngressProtocol.MIPLAY)
        if miplay_runtime is not None:
            suite.set_ingress(
                IngressProtocol.MIPLAY,
                IngressState.STOPPED,
                handle=None,
                port=miplay_runtime.port,
            )
        if self.airplay_manager:
            await self.airplay_manager.stop_for_speaker(suite.controller_id)
        airplay = suite.get_ingress(IngressProtocol.AIRPLAY)
        if airplay is not None:
            suite.set_ingress(
                IngressProtocol.AIRPLAY,
                IngressState.STOPPED,
                handle=None,
                port=airplay.port,
            )

        renderer_runtime = suite.get_ingress(IngressProtocol.DLNA)
        renderer = renderer_runtime.handle if renderer_runtime else None
        if renderer is not None:
            if self.ssdp_server:
                await self.ssdp_server.unregister_renderer(renderer.udn)
            if self.device_server:
                await self.device_server.unregister_renderer(renderer.udn)
            self.renderers.pop(renderer.udn, None)
            self._did_to_udn.pop(suite.controller_id, None)
        suite.set_ingress(
            IngressProtocol.DLNA,
            IngressState.STOPPED,
            handle=None,
            port=self.config.dlna_port,
        )

    async def set_target_enabled(
        self,
        target_id: str,
        enabled: bool,
    ) -> ReceiverSuite | None:
        """Transactionally enable or disable one already registered suite."""
        target = self.config.get_target(target_id)
        if target is None:
            raise KeyError(target_id)
        suite = self.suite_registry.get(target.id)
        if suite is None and not enabled:
            target.enabled = False
            self.config.save()
            return None
        if suite is None and not self.dlna_running:
            original = target.enabled
            target.enabled = True
            await self._start_dlna_services()
            suite = self.suite_registry.get(target.id)
            if suite is None:
                target.enabled = original
                self.config.save()
                raise RuntimeError("SUITE_ENABLE_FAILED")
            self.config.save()
            return suite
        if suite is None:
            controller_id, controller = await self.speaker_manager.add_target(target)
            suite = self.suite_registry.register(target, controller_id, controller)
        suite = await self.suite_registry.set_enabled(
            target_id,
            enabled,
            start=self._start_receiver_suite,
            stop=self._stop_receiver_suite,
        )
        self.config.save()
        return suite

    def _miplay_port_for_target(self, target_id: str) -> int:
        """Return a stable port slot based on all persisted target IDs."""
        base = self.config.miplay_port
        if base == 0:
            return 0
        target_ids = sorted(self.config.targets)
        try:
            slot = target_ids.index(target_id)
        except ValueError:
            slot = 0
        return base + slot

    async def _start_miplay_for_speakers(self):
        """Start one isolated native MiPlay ingress per registered suite."""
        if not self.config.enable_miplay:
            log.info("MiPlay 接收服务已禁用")
            for suite in self.suite_registry.values():
                self.suite_registry.set_ingress(
                    suite.target.id,
                    IngressProtocol.MIPLAY,
                    IngressState.STOPPED,
                    port=self._miplay_port_for_target(suite.target.id),
                )
            return
        for suite in self.suite_registry.values():
            if suite.target.enabled and suite.target.id not in self.miplay_receivers:
                await self._start_miplay_for_target(
                    suite,
                    self._miplay_port_for_target(suite.target.id),
                )

    async def _start_miplay_for_speaker(self):
        """Compatibility wrapper retained for the migration release."""
        await self._start_miplay_for_speakers()

    async def _start_miplay_for_target(
        self,
        suite: ReceiverSuite,
        port: int,
    ) -> MiPlayReceiver | None:
        target_id = suite.target.id
        if port > 65535:
            self.suite_registry.set_ingress(
                target_id,
                IngressProtocol.MIPLAY,
                IngressState.UNAVAILABLE,
                port=port,
                error_code="MIPLAY_PORT_OUT_OF_RANGE",
            )
            log.error("MiPlay 端口超出范围: target=%s port=%s", target_id, port)
            return None
        existing = self.miplay_receivers.get(target_id)
        if existing is not None:
            return existing
        controller = suite.controller
        stable_id = uuid.uuid5(uuid.NAMESPACE_URL, f"castfabric-miplay:{target_id}")
        identity = MiPlayIdentity(
            address=self.config.hostname,
            friendly_name=suite.target.get_receiver_alias(
                self.config.device_name_prefix
            ),
            instance=f"{PRODUCT_NAME}-{stable_id.hex[:8]}",
            host=f"{PRODUCT_SLUG}-{stable_id.hex[:8]}",
            device_id=stable_id,
            control_port=port,
        )
        receiver = MiPlayReceiver(
            host="0.0.0.0",
            port=port,
            sink_factory=lambda: CastFabricLiveAudioSink(
                self.config.hostname,
                controller,
                audio_format=self.config.miplay_stream_format,
                play_type=self.config.miplay_play_type,
                http_mode=self.config.miplay_http_mode,
                content_type=self.config.miplay_content_type,
                lifecycle_callback=lambda event, details: self._handle_miplay_output_lifecycle(
                    target_id,
                    event,
                    details,
                ),
            ),
            volume_setter=controller.set_volume,
            identity=identity,
            advertise_address=self.config.hostname,
            lifecycle_callback=lambda event, details: self._handle_miplay_lifecycle(
                target_id,
                event,
                details,
            ),
        )
        self.suite_registry.set_ingress(
            target_id,
            IngressProtocol.MIPLAY,
            IngressState.STARTING,
            handle=receiver,
            port=port,
        )
        try:
            await receiver.start()
        except Exception as exc:
            diagnostics = (
                receiver.diagnostics()
                if hasattr(receiver, "diagnostics")
                else {"running": False}
            )
            error_code = (
                "MIPLAY_PORT_BIND_FAILED"
                if isinstance(exc, OSError) and not diagnostics.get("running")
                else "MIPLAY_START_FAILED"
            )
            log.error(
                "启动 MiPlay 接收服务失败: target=%s error=%s code=%s",
                target_id,
                type(exc).__name__,
                error_code,
            )
            await receiver.stop()
            self.suite_registry.set_ingress(
                target_id,
                IngressProtocol.MIPLAY,
                IngressState.UNAVAILABLE,
                handle=None,
                port=port,
                error_code=error_code,
            )
            return None
        self.miplay_receivers[target_id] = receiver
        self.suite_registry.set_ingress(
            target_id,
            IngressProtocol.MIPLAY,
            IngressState.READY,
            handle=receiver,
            port=receiver.port,
        )
        log.info(
            "MiPlay 网关已映射到音箱: %s (target=%s port=%s)",
            suite.target.name,
            target_id,
            receiver.port,
        )
        return receiver

    async def _handle_miplay_output_lifecycle(
        self,
        target_id: str,
        event: str,
        details: dict,
    ) -> None:
        """Record verified output-boundary facts with the journal allowlist."""
        suite = self.suite_registry.get(target_id)
        if suite is None:
            return
        suite.last_activity_at = datetime.now(timezone.utc)
        failed = event == "output_failed"
        outcome = (
            EventOutcome.FAILED
            if failed
            else EventOutcome.SUCCESS
            if event == "output_started"
            else EventOutcome.INFO
        )
        self.activity_journal.append(
            target_id=target_id,
            session_id=suite.current_session_id,
            protocol=IngressProtocol.MIPLAY,
            type=f"miplay.{event}",
            outcome=outcome,
            summary_key=f"activity.miplay_{event}",
            reason_code=details.get("reason") if failed else None,
            details=details,
        )

    async def _handle_miplay_lifecycle(
        self,
        target_id: str,
        event: str,
        details: dict,
    ) -> None:
        """Project receiver facts into sessions without guessing a source App."""
        suite = self.suite_registry.get(target_id)
        if suite is None:
            return
        if event == "session_started":
            session = await self.session_coordinator.begin(
                target_id,
                IngressProtocol.MIPLAY,
                media_format=details.get("media_format"),
            )
            self._miplay_session_ids[target_id] = session.id
            suite.current_session_id = session.id
            suite.last_activity_at = datetime.now(timezone.utc)
            suite.set_ingress(
                IngressProtocol.MIPLAY,
                IngressState.ACTIVE,
            )
            return
        session_id = self._miplay_session_ids.get(target_id)
        if event == "media_started" and session_id:
            await self.session_coordinator.transition(session_id, SessionState.PLAYING)
            suite.last_activity_at = datetime.now(timezone.utc)
            return
        if event == "session_ended" and session_id:
            await self.session_coordinator.end(
                session_id,
                failed=bool(details.get("failed")),
            )
            self._miplay_session_ids.pop(target_id, None)
            suite.current_session_id = None
            suite.last_activity_at = datetime.now(timezone.utc)
            runtime = suite.get_ingress(IngressProtocol.MIPLAY)
            suite.set_ingress(
                IngressProtocol.MIPLAY,
                IngressState.READY if suite.target.enabled else IngressState.STOPPED,
                handle=runtime.handle if runtime else None,
                port=runtime.port if runtime else None,
            )

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
        if self.miplay_receivers:
            receivers = list(self.miplay_receivers.values())
            self.miplay_receivers.clear()
            await asyncio.gather(
                *(receiver.stop() for receiver in receivers),
                return_exceptions=True,
            )
        self._miplay_session_ids.clear()
        if self.ssdp_server:
            await self.ssdp_server.stop()
            self.ssdp_server = None
        if self.device_server:
            await self.device_server.stop()
            self.device_server = None
        self.renderers.clear()
        self._did_to_udn.clear()
        self.suite_registry.clear()
        self.dlna_running = False

    async def stop(self):
        """停止所有服务"""
        log.info("%s 正在关闭...", PRODUCT_NAME)

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

        log.info("%s 已关闭", PRODUCT_NAME)

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


# Compatibility boundary for existing imports and third-party integrations.
MiAir = CastFabric
