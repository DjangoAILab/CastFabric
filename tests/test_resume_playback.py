import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from miair.const import TRANSPORT_STATE_PAUSED, TRANSPORT_STATE_STOPPED
from miair.dlna.device_server import DeviceServer, _MAX_BUFFERS
from miair.dlna.media_buffer import MediaBuffer
from miair.dlna.renderer import DLNARenderer


def completed_buffer(url: str, size: int = 32) -> MediaBuffer:
    buf = MediaBuffer(url)
    buf.data = bytearray(size)
    buf.total_size = size
    buf.download_complete = True
    buf._headers_event.set()
    buf._complete_event.set()
    return buf


class ResumePlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        server = getattr(self, "server", None)
        if server and server._proxy_session and not server._proxy_session.closed:
            await server._proxy_session.close()

    async def test_seek_waits_for_new_buffer_headers_and_completion(self):
        self.server = DeviceServer("127.0.0.1", 8200)
        url = "https://example.invalid/song.mp3"
        buffer_id = "source"
        buf = MediaBuffer(url)
        self.server._media_buffers[buffer_id] = buf
        self.server._url_to_buffer[url] = buffer_id

        async def finish_download():
            await asyncio.sleep(0.01)
            data = bytearray(16_000)
            for offset in range(0, len(data), 1_000):
                data[offset : offset + 2] = b"\xff\xfb"
            buf.data = data
            buf.total_size = len(data)
            buf.content_type = "audio/mpeg"
            buf.download_complete = True
            buf._headers_event.set()
            buf._complete_event.set()

        download_task = asyncio.create_task(finish_download())
        self.server._ffmpeg_seek = AsyncMock(return_value=None)

        seek_url = await self.server.create_seek_url(url, 50.0, 100.0, "udn")
        await download_task

        self.assertIsNotNone(seek_url)
        self.assertIn("/media/", seek_url)

    async def test_count_cleanup_preserves_current_source_buffer(self):
        self.server = DeviceServer("127.0.0.1", 8200)
        current_url = "https://example.invalid/current.mp3"
        self.server.renderers["udn"] = SimpleNamespace(
            current_uri=current_url,
            next_uri="",
        )
        self.server._media_buffers["current"] = completed_buffer(current_url)
        self.server._url_to_buffer[current_url] = "current"

        for index in range(_MAX_BUFFERS - 1):
            buffer_id = f"old-{index}"
            self.server._media_buffers[buffer_id] = completed_buffer(
                f"https://example.invalid/{index}.mp3"
            )

        self.server._cleanup_old_buffers()

        self.assertIn("current", self.server._media_buffers)
        self.assertLess(len(self.server._media_buffers), _MAX_BUFFERS)

    async def test_memory_cleanup_preserves_current_source_buffer(self):
        self.server = DeviceServer("127.0.0.1", 8200)
        self.server._max_buffer_memory = 10
        current_url = "https://example.invalid/current.mp3"
        self.server.renderers["udn"] = SimpleNamespace(
            current_uri=current_url,
            next_uri="",
        )
        self.server._media_buffers["current"] = completed_buffer(current_url, 8)
        self.server._url_to_buffer[current_url] = "current"
        self.server._media_buffers["disposable"] = completed_buffer(
            "https://example.invalid/disposable.mp3", 8
        )

        self.server._cleanup_by_memory()

        self.assertIn("current", self.server._media_buffers)
        self.assertNotIn("disposable", self.server._media_buffers)

    async def test_resume_does_not_fall_back_when_seek_url_is_unavailable(self):
        speaker = SimpleNamespace(
            did="did",
            speaker=SimpleNamespace(hardware="M01"),
            play_url=AsyncMock(return_value=True),
        )
        renderer = DLNARenderer(
            "udn",
            "M01",
            speaker,
            config=SimpleNamespace(follow_device_volume=True),
        )
        renderer.current_uri = "https://example.invalid/current.mp3"
        renderer.transport_state = TRANSPORT_STATE_PAUSED
        renderer._accumulated_time = 187.0
        renderer._track_duration = 320.0
        renderer.proxy_url_func = lambda *_: "http://127.0.0.1:8200/media/plain"
        renderer.seek_url_func = AsyncMock(return_value=None)

        success = await renderer.play()

        self.assertFalse(success)
        self.assertEqual(renderer.transport_state, TRANSPORT_STATE_STOPPED)
        speaker.play_url.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
