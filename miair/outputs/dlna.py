"""Native UPnP MediaRenderer output adapter."""

from __future__ import annotations

from miair.dlna.client import LocalDLNAClient
from miair.outputs.base import PlaybackTargetInfo


class DLNAOutputAdapter:
    def __init__(self, target_id: str, name: str, client: LocalDLNAClient):
        self.info = PlaybackTargetInfo(target_id, name, "dlna")
        self.client = client

    async def play_url(self, url: str, *, play_type: int = 2) -> bool:
        del play_type
        return bool(await self.client.play_url(url))

    async def pause(self) -> bool:
        return bool(await self.client.pause())

    async def stop(self) -> bool:
        return bool(await self.client.stop())

    async def set_volume(self, volume: int) -> bool:
        return bool(await self.client.set_volume(max(0, min(100, volume))))

    async def get_volume(self) -> int:
        return int(await self.client.get_volume())

    async def get_status(self) -> dict:
        return await self.client.get_status()

