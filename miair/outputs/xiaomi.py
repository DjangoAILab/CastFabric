"""Optional Xiaomi MiNA cloud output adapter."""

from __future__ import annotations

import json
import logging

from miair.config import Speaker
from miair.const import DEFAULT_AUDIO_ID
from miair.outputs.base import PlaybackTargetInfo


log = logging.getLogger("miair")


class XiaomiOutputAdapter:
    """Keep vendor-specific playback semantics outside the CastFabric core."""

    _STOP_AS_PAUSE_HARDWARE = {"M01", "XMYX01JY"}

    def __init__(self, speaker: Speaker, auth):
        self.speaker = speaker
        self.auth = auth
        self.info = PlaybackTargetInfo(
            f"xiaomi:{speaker.did}", speaker.get_dlna_name(), "xiaomi-mina"
        )
        self._last_volume = 50

    @property
    def device_id(self) -> str:
        return self.speaker.device_id

    def should_use_music_api(self) -> bool:
        return not self.speaker.is_compatibility_mode()

    def should_stop_for_pause(self) -> bool:
        if self.should_use_music_api():
            return True
        hardware = self.speaker.hardware or ""
        return any(model in hardware for model in self._STOP_AS_PAUSE_HARDWARE)

    @staticmethod
    def request_succeeded(ret) -> bool:
        if not isinstance(ret, dict) or ret.get("code") != 0:
            return False
        data = ret.get("data")
        return not isinstance(data, dict) or data.get("code", 0) == 0

    @staticmethod
    def _is_login_error(exc: Exception) -> bool:
        message = str(exc)
        return "Login failed" in message or "登录验证失败" in message

    async def _retry_login(self) -> None:
        self.auth._logged_in = False
        await self.auth.login()
        await self.auth.ensure_login()

    async def _play_once(self, url: str, play_type: int) -> bool:
        await self.auth.ensure_login()
        if self.should_use_music_api():
            ret = await self.auth.mina_service.play_by_music_url(
                self.device_id,
                url,
                _type=play_type,
                audio_id=DEFAULT_AUDIO_ID,
            )
        else:
            ret = await self.auth.mina_service.play_by_url(
                self.device_id, url, _type=play_type
            )
        return self.request_succeeded(ret)

    async def play_url(self, url: str, *, play_type: int = 2) -> bool:
        try:
            return await self._play_once(url, play_type)
        except Exception as exc:
            if not self._is_login_error(exc):
                raise
            await self._retry_login()
            return await self._play_once(url, play_type)

    async def _pause_once(self) -> bool:
        await self.auth.ensure_login()
        if self.should_stop_for_pause():
            ret = await self.auth.mina_service.player_stop(self.device_id)
        else:
            ret = await self.auth.mina_service.player_pause(self.device_id)
        return self.request_succeeded(ret)

    async def pause(self) -> bool:
        try:
            return await self._pause_once()
        except Exception as exc:
            if not self._is_login_error(exc):
                raise
            await self._retry_login()
            return await self._pause_once()

    async def resume(self) -> bool:
        return False

    async def _stop_once(self) -> bool:
        await self.auth.ensure_login()
        ret = await self.auth.mina_service.player_stop(self.device_id)
        if not self.request_succeeded(ret):
            return False
        return await self._pause_once()

    async def stop(self) -> bool:
        try:
            return await self._stop_once()
        except Exception as exc:
            if not self._is_login_error(exc):
                raise
            await self._retry_login()
            return await self._stop_once()

    async def _set_volume_once(self, volume: int) -> bool:
        await self.auth.ensure_login()
        await self.auth.mina_service.player_set_volume(self.device_id, volume)
        if volume > 0:
            self._last_volume = volume
        return True

    async def set_volume(self, volume: int) -> bool:
        volume = max(0, min(100, volume))
        try:
            return await self._set_volume_once(volume)
        except Exception as exc:
            if not self._is_login_error(exc):
                raise
            await self._retry_login()
            return await self._set_volume_once(volume)

    async def seek(self, position_seconds: int) -> bool:
        del position_seconds
        return False

    async def _get_volume_once(self) -> int:
        await self.auth.ensure_login()
        status = await self.auth.mina_service.player_get_status(self.device_id)
        info = json.loads(status.get("data", {}).get("info", "{}"))
        volume = int(info.get("volume", 0))
        if volume > 0:
            self._last_volume = volume
        return volume

    async def get_volume(self) -> int:
        try:
            return await self._get_volume_once()
        except Exception as exc:
            if not self._is_login_error(exc):
                log.warning("小米云读取音量失败: %s", type(exc).__name__)
                return self._last_volume
            await self._retry_login()
            return await self._get_volume_once()

    async def _get_status_once(self) -> dict:
        await self.auth.ensure_login()
        response = await self.auth.mina_service.player_get_status(self.device_id)
        if response.get("code") != 0:
            raise RuntimeError(f"MiNA status error: {response.get('code')}")
        info_text = response.get("data", {}).get("info")
        if not info_text:
            raise RuntimeError("MiNA status response has no info")
        info = json.loads(info_text)
        return {
            "status": info.get("status", 0),
            "volume": int(info.get("volume", 0)),
        }

    async def get_status(self) -> dict:
        try:
            return await self._get_status_once()
        except Exception as exc:
            if not self._is_login_error(exc):
                raise
            await self._retry_login()
            return await self._get_status_once()
