import asyncio
import shutil
import struct
import subprocess

import pytest

from miair.miplay.media import (
    FfmpegMpegTsDecoder,
    MediaFrameBuffer,
    MediaProtocolError,
    RecordingPcmSink,
    decode_rtp_mpegts,
    encode_media_frame,
    encode_rtp_mpegts,
)


def make_ts_packet(pid=0x1100):
    return bytes([0x47, 0x40 | ((pid >> 8) & 0x1F), pid & 0xFF, 0x10]) + b"\xff" * 184


def test_media_envelope_and_rtp_decode_incrementally():
    transport_stream = make_ts_packet()
    rtp = encode_rtp_mpegts(7, 1920, 0xDEADBEEF, transport_stream)
    wire = encode_media_frame(rtp)
    parser = MediaFrameBuffer()

    assert parser.feed(wire[:3]) == []
    assert parser.feed(wire[3:-1]) == []
    frames = parser.feed(wire[-1:])
    assert len(frames) == 1

    packet = decode_rtp_mpegts(frames[0])
    assert packet.sequence == 7
    assert packet.timestamp == 1920
    assert packet.ssrc == 0xDEADBEEF
    assert packet.transport_stream == transport_stream


def test_rtp_rejects_wrong_payload_type_and_unaligned_transport_stream():
    packet = bytearray(encode_rtp_mpegts(1, 2, 3, make_ts_packet()))
    packet[1] = 96
    with pytest.raises(MediaProtocolError, match="payload type"):
        decode_rtp_mpegts(packet)

    with pytest.raises(MediaProtocolError, match="188"):
        encode_rtp_mpegts(1, 2, 3, b"short")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_ffmpeg_decoder_delivers_non_silent_48khz_stereo_pcm():
    encoded = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.25",
            "-ac",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-f",
            "mpegts",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout

    async def run():
        sink = RecordingPcmSink()
        decoder = FfmpegMpegTsDecoder(sink)
        await decoder.start()
        await decoder.write(encoded)
        await decoder.stop()
        return sink

    sink = asyncio.run(run())
    pcm = b"".join(sink.chunks)
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)

    assert sink.sample_rate == 48_000
    assert sink.channels == 2
    assert len(pcm) >= 48_000 * 2 * 2 // 10
    assert max(abs(value) for value in samples) > 500
