from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from miair.outputs.base import FallbackPlaybackTarget, PlaybackTargetInfo
from miair.outputs.dlna import DLNAOutputAdapter


class FakeTarget:
    def __init__(self, target_id, *, play=True, error=None):
        self.info = PlaybackTargetInfo(target_id, target_id, "fake")
        self.play_result = play
        self.error = error
        self.play_url = AsyncMock(side_effect=self._play)
        self.pause = AsyncMock(return_value=True)
        self.stop = AsyncMock(return_value=True)
        self.set_volume = AsyncMock(return_value=True)
        self.get_volume = AsyncMock(return_value=25)
        self.get_status = AsyncMock(return_value={"status": 1, "volume": 25})

    async def _play(self, url, *, play_type=2):
        if self.error:
            raise self.error
        return self.play_result


@pytest.mark.asyncio
async def test_dlna_adapter_ignores_vendor_play_type():
    client = SimpleNamespace(play_url=AsyncMock(return_value=True))
    target = DLNAOutputAdapter(
        target_id="uuid:renderer",
        name="Living Room",
        client=client,
    )

    assert await target.play_url("http://gateway/audio.wav", play_type=0)
    client.play_url.assert_awaited_once_with("http://gateway/audio.wav")
    assert target.info.kind == "dlna"


@pytest.mark.asyncio
async def test_fallback_uses_next_adapter_after_primary_exception():
    primary = FakeTarget("local", error=OSError("offline"))
    fallback = FakeTarget("cloud")
    target = FallbackPlaybackTarget([primary, fallback])

    assert await target.play_url("http://gateway/audio.wav", play_type=1)
    primary.play_url.assert_awaited_once()
    fallback.play_url.assert_awaited_once_with(
        "http://gateway/audio.wav", play_type=1
    )
    assert target.active_target_id == "cloud"


@pytest.mark.asyncio
async def test_query_raises_when_every_adapter_is_unavailable():
    first = FakeTarget("one")
    second = FakeTarget("two")
    first.get_status.side_effect = OSError("one offline")
    second.get_status.side_effect = OSError("two offline")
    target = FallbackPlaybackTarget([first, second])

    with pytest.raises(RuntimeError, match="get_status failed"):
        await target.get_status()

