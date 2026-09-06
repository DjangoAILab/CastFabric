"""Protocol-neutral playback target contract and failover composition."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


log = logging.getLogger("miair")


@dataclass(frozen=True)
class PlaybackTargetInfo:
    id: str
    name: str
    kind: str


@runtime_checkable
class PlaybackTarget(Protocol):
    info: PlaybackTargetInfo

    async def play_url(self, url: str, *, play_type: int = 2) -> bool: ...

    async def pause(self) -> bool: ...

    async def resume(self) -> bool: ...

    async def stop(self) -> bool: ...

    async def set_volume(self, volume: int) -> bool: ...

    async def seek(self, position_seconds: int) -> bool: ...

    async def get_volume(self) -> int: ...

    async def get_status(self) -> dict: ...


class UnavailablePlaybackTarget:
    """Stable placeholder that keeps ingress discovery alive while output is offline."""

    def __init__(self, target_id: str, name: str):
        self.info = PlaybackTargetInfo(target_id, name, "unavailable")

    async def play_url(self, url: str, *, play_type: int = 2) -> bool:
        return False

    async def pause(self) -> bool:
        return False

    async def resume(self) -> bool:
        return False

    async def stop(self) -> bool:
        return False

    async def set_volume(self, volume: int) -> bool:
        return False

    async def seek(self, position_seconds: int) -> bool:
        del position_seconds
        return False

    async def get_volume(self) -> int:
        raise RuntimeError("playback target is unavailable")

    async def get_status(self) -> dict:
        raise RuntimeError("playback target is unavailable")


class FallbackPlaybackTarget:
    """Try output adapters in priority order and remember the active one."""

    def __init__(self, targets: list[PlaybackTarget]):
        if not targets:
            raise ValueError("at least one playback target is required")
        self.targets = list(targets)
        self.info = self.targets[0].info
        self.active_target_id: str | None = None

    def _ordered_targets(self) -> list[PlaybackTarget]:
        if not self.active_target_id:
            return self.targets
        return sorted(
            self.targets,
            key=lambda target: target.info.id != self.active_target_id,
        )

    async def _command(self, method: str, *args, **kwargs) -> bool:
        for target in self._ordered_targets():
            try:
                accepted = await getattr(target, method)(*args, **kwargs)
            except Exception as exc:
                log.warning(
                    "输出适配器 %s 执行 %s 失败: %s",
                    target.info.id,
                    method,
                    type(exc).__name__,
                )
                continue
            if accepted:
                self.active_target_id = target.info.id
                return True
        return False

    async def _query(self, method: str):
        errors = []
        for target in self._ordered_targets():
            try:
                result = await getattr(target, method)()
            except Exception as exc:
                errors.append(f"{target.info.id}:{type(exc).__name__}")
                continue
            self.active_target_id = target.info.id
            return result
        detail = ", ".join(errors) or "no adapters"
        raise RuntimeError(f"{method} failed on every output adapter ({detail})")

    async def play_url(self, url: str, *, play_type: int = 2) -> bool:
        return await self._command("play_url", url, play_type=play_type)

    async def pause(self) -> bool:
        return await self._command("pause")

    async def resume(self) -> bool:
        return await self._command("resume")

    async def stop(self) -> bool:
        return await self._command("stop")

    async def set_volume(self, volume: int) -> bool:
        return await self._command("set_volume", max(0, min(100, volume)))

    async def seek(self, position_seconds: int) -> bool:
        return await self._command("seek", position_seconds)

    async def get_volume(self) -> int:
        return int(await self._query("get_volume"))

    async def get_status(self) -> dict:
        return await self._query("get_status")
