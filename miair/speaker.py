"""Legacy speaker facade over CastFabric playback output adapters."""

from __future__ import annotations

import logging
import uuid

from miair.auth import AuthManager
from miair.config import Config, Speaker
from miair.dlna.client import LocalDLNAClient
from miair.outputs.base import FallbackPlaybackTarget, UnavailablePlaybackTarget
from miair.outputs.dlna import DLNAOutputAdapter
from miair.outputs.xiaomi import XiaomiOutputAdapter


log = logging.getLogger("miair")


class SpeakerController:
    """Compatibility facade used by existing ingress implementations.

    Native DLNA is the primary output. Xiaomi MiNA remains an optional fallback
    adapter until generic target configuration replaces the legacy speaker model.
    """

    _STOP_AS_PAUSE_HARDWARE = XiaomiOutputAdapter._STOP_AS_PAUSE_HARDWARE

    def __init__(
        self,
        speaker: Speaker,
        auth: AuthManager | None,
        local_dlna: LocalDLNAClient | None = None,
    ):
        self.speaker = speaker
        self.auth = auth
        self.local_dlna = local_dlna
        self.cloud_output = XiaomiOutputAdapter(speaker, auth) if auth else None
        adapters = []
        if local_dlna is not None:
            adapters.append(
                DLNAOutputAdapter(
                    target_id=f"dlna:{speaker.device_id}",
                    name=speaker.get_dlna_name(),
                    client=local_dlna,
                )
            )
        if self.cloud_output is not None:
            adapters.append(self.cloud_output)
        if not adapters:
            adapters.append(
                UnavailablePlaybackTarget(
                    f"unavailable:{speaker.did}", speaker.get_dlna_name()
                )
            )
        self.output = FallbackPlaybackTarget(adapters)

    @property
    def device_id(self) -> str:
        return self.speaker.device_id

    @property
    def did(self) -> str:
        return self.speaker.did

    def _should_use_music_api(self) -> bool:
        return bool(self.cloud_output and self.cloud_output.should_use_music_api())

    def _should_stop_for_pause(self) -> bool:
        return bool(self.cloud_output and self.cloud_output.should_stop_for_pause())

    @staticmethod
    def _mina_request_succeeded(ret) -> bool:
        return XiaomiOutputAdapter.request_succeeded(ret)

    async def play_url(self, url: str, *, play_type: int = 2) -> bool:
        return await self.output.play_url(url, play_type=play_type)

    async def pause(self) -> bool:
        return await self.output.pause()

    async def stop(self) -> bool:
        return await self.output.stop()

    async def set_volume(self, volume: int) -> bool:
        return await self.output.set_volume(volume)

    async def get_volume(self) -> int:
        return await self.output.get_volume()

    async def get_status(self) -> dict:
        return await self.output.get_status()


class SpeakerManager:
    """Build compatibility controllers from cached MiAir speaker records."""

    def __init__(self, config: Config, auth: AuthManager):
        self.config = config
        self.auth = auth
        self.controllers: dict[str, SpeakerController] = {}

    async def init_speakers(self, *, refresh_from_cloud: bool = True):
        if refresh_from_cloud:
            await self.auth.update_speakers_info()
        elif any(target.legacy_did for target in self.config.get_enabled_targets()):
            log.warning("小米云认证不可用，使用本地缓存的输出目标信息")
        else:
            log.info("使用标准 DLNA 输出目标，不需要厂商云认证")

        self.controllers.clear()
        for target in self.config.get_enabled_targets():
            if target.legacy_did:
                speaker = self.config.get_speaker(target.legacy_did)
            else:
                if not target.virtual_udn:
                    target.virtual_udn = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"castfabric-output:{target.id}",
                        )
                    )
                speaker = Speaker(
                    did=target.id,
                    device_id=target.udn,
                    name=target.name,
                    dlna_name=target.name,
                    udn=target.virtual_udn,
                    local_dlna_location=target.location,
                    enabled=target.enabled,
                )
            local_dlna = await LocalDLNAClient.connect(
                target.udn,
                self.config.hostname,
                target.location,
            )
            if local_dlna:
                target.location = local_dlna.location
                speaker.local_dlna_location = local_dlna.location
                log.info(
                    "已连接实体音箱本地 DLNA: %s (%s)",
                    speaker.get_dlna_name(),
                    local_dlna.location,
                )

            controller_id = target.legacy_did or target.id
            cloud_auth = (
                self.auth
                if target.legacy_did and self.config.enable_xiaomi_extension
                else None
            )
            self.controllers[controller_id] = SpeakerController(
                speaker, cloud_auth, local_dlna=local_dlna
            )
            log.info(
                "已初始化输出控制器: %s (target=%s)",
                speaker.get_dlna_name(),
                target.id,
            )

    def get_controller(self, did: str) -> SpeakerController | None:
        return self.controllers.get(did)

    def get_controller_by_udn(self, udn: str) -> SpeakerController | None:
        for controller in self.controllers.values():
            if controller.speaker.udn == udn:
                return controller
        return None
