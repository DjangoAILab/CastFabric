"""Bounded, one-time file uploads for ephemeral output playback."""

from __future__ import annotations

import asyncio
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import AsyncIterable, Callable


class FilePlaybackError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PendingUpload:
    id: str
    target_id: str
    filename: str
    content_type: str
    size_bytes: int
    expires_at: float


@dataclass(frozen=True)
class MediaFile:
    token: str
    target_id: str
    filename: str
    content_type: str
    path: Path


class EphemeralMediaStore:
    DEFAULT_MAX_BYTES = 64 * 1024 * 1024

    def __init__(
        self,
        playback_service,
        *,
        directory: str | Path | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        upload_ttl: float = 300.0,
        media_ttl: float = 6 * 60 * 60,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ):
        self.playback_service = playback_service
        self.max_bytes = int(max_bytes)
        self.upload_ttl = float(upload_ttl)
        self.media_ttl = float(media_ttl)
        self.clock = clock
        self.id_factory = id_factory
        self._temporary_directory = (
            tempfile.TemporaryDirectory(prefix="castfabric-media-")
            if directory is None
            else None
        )
        self.directory = Path(
            self._temporary_directory.name if self._temporary_directory else directory
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self._uploads: dict[str, PendingUpload] = {}
        self._media: dict[str, MediaFile] = {}
        self._media_expiry: dict[str, asyncio.TimerHandle] = {}
        self._pulled_media: set[str] = set()

    def _expire_media_token(self, token: str) -> None:
        self._media_expiry.pop(token, None)
        media = self._media.pop(token, None)
        self._pulled_media.discard(token)
        if media is not None:
            media.path.unlink(missing_ok=True)

    @staticmethod
    def _safe_filename(value: str) -> str:
        filename = PurePath(str(value or "").replace("\x00", "")).name.strip()
        if not filename:
            raise FilePlaybackError("INVALID_FILENAME")
        return filename[:255]

    def _expire_uploads(self) -> None:
        now = self.clock()
        self._uploads = {
            key: upload
            for key, upload in self._uploads.items()
            if upload.expires_at > now
        }

    def create_upload(
        self,
        target_id: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> dict:
        self._expire_uploads()
        self.playback_service.controller_for(target_id)
        try:
            size = int(size_bytes)
        except (TypeError, ValueError) as exc:
            raise FilePlaybackError("INVALID_FILE_SIZE") from exc
        if size <= 0 or size > self.max_bytes:
            raise FilePlaybackError("INVALID_FILE_SIZE")
        upload_id = self.id_factory()
        upload = PendingUpload(
            id=upload_id,
            target_id=str(target_id),
            filename=self._safe_filename(filename),
            content_type=str(content_type or "application/octet-stream")[:120],
            size_bytes=size,
            expires_at=self.clock() + self.upload_ttl,
        )
        self._uploads[upload_id] = upload
        return {
            "upload_id": upload_id,
            "upload_path": f"/api/v1/playback/files/{upload_id}",
            "expires_in": int(self.upload_ttl),
            "max_bytes": self.max_bytes,
        }

    async def accept_upload(
        self,
        upload_id: str,
        chunks: AsyncIterable[bytes],
        *,
        origin: str,
    ) -> dict:
        self._expire_uploads()
        upload = self._uploads.pop(upload_id, None)
        if upload is None:
            raise FilePlaybackError("UPLOAD_NOT_FOUND")
        media_token = self.id_factory()
        path = self.directory / media_token
        written = 0
        try:
            with path.open("xb") as output:
                async for chunk in chunks:
                    payload = bytes(chunk)
                    written += len(payload)
                    if written > upload.size_bytes or written > self.max_bytes:
                        raise FilePlaybackError("UPLOAD_SIZE_MISMATCH")
                    output.write(payload)
            if written != upload.size_bytes:
                raise FilePlaybackError("UPLOAD_SIZE_MISMATCH")
            await self.cleanup_target(upload.target_id)
            media = MediaFile(
                token=media_token,
                target_id=upload.target_id,
                filename=upload.filename,
                content_type=upload.content_type,
                path=path,
            )
            self._media[media_token] = media
            media_url = (
                origin.rstrip("/")
                + f"/api/v1/playback/media/{media_token}"
            )
            result = await self.playback_service.play_url(
                upload.target_id,
                media_url,
                media_format=upload.content_type,
            )
            self._media_expiry[media_token] = (
                asyncio.get_running_loop().call_later(
                    self.media_ttl,
                    self._expire_media_token,
                    media_token,
                )
            )
            return result
        except Exception:
            handle = self._media_expiry.pop(media_token, None)
            if handle is not None:
                handle.cancel()
            self._media.pop(media_token, None)
            path.unlink(missing_ok=True)
            raise

    def resolve_media(self, token: str) -> MediaFile:
        media = self._media.get(token)
        if media is None or not media.path.is_file():
            raise FilePlaybackError("MEDIA_NOT_FOUND")
        return media

    def confirm_pull(self, token: str) -> tuple[MediaFile, bool]:
        media = self.resolve_media(token)
        first_pull = token not in self._pulled_media
        self._pulled_media.add(token)
        return media, first_pull

    async def cleanup_target(self, target_id: str) -> None:
        tokens = [
            token for token, media in self._media.items() if media.target_id == target_id
        ]
        for token in tokens:
            handle = self._media_expiry.pop(token, None)
            if handle is not None:
                handle.cancel()
            self._pulled_media.discard(token)
            media = self._media.pop(token)
            media.path.unlink(missing_ok=True)

    async def cleanup_all(self) -> None:
        self._uploads.clear()
        for handle in self._media_expiry.values():
            handle.cancel()
        self._media_expiry.clear()
        self._pulled_media.clear()
        for media in self._media.values():
            media.path.unlink(missing_ok=True)
        self._media.clear()

    async def close(self) -> None:
        await self.cleanup_all()
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
