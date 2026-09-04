"""Managed-file and external-URL media asset application service."""

from __future__ import annotations

import hashlib
import secrets
import time
import wave
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, AsyncIterable, Callable
from urllib.parse import urlsplit

from miair.runtime.redaction import redact_url


class ContentServiceError(RuntimeError):
    def __init__(self, code: str, reason: str, details: dict[str, Any] | None = None):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.details = details or {}


@dataclass(frozen=True)
class PendingMediaUpload:
    id: str
    filename: str
    content_type: str
    size_bytes: int
    display_name: str
    expires_at: float


class MediaAssetService:
    DEFAULT_MAX_BYTES = 256 * 1024 * 1024
    _CONTENT_TYPES = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
        "ogg": "audio/ogg",
        "aac": "audio/aac",
        "m4a": "audio/mp4",
        "wma": "audio/x-ms-wma",
    }

    def __init__(
        self,
        repository,
        directory: str | Path,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        upload_ttl: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ):
        self.repository = repository
        self.directory = Path(directory)
        self.blob_directory = self.directory / "blobs"
        self.upload_directory = self.directory / "uploads"
        self.blob_directory.mkdir(parents=True, exist_ok=True)
        self.upload_directory.mkdir(parents=True, exist_ok=True)
        self.max_bytes = int(max_bytes)
        self.upload_ttl = float(upload_ttl)
        self.clock = clock
        self.id_factory = id_factory
        self._uploads: dict[str, PendingMediaUpload] = {}

    @staticmethod
    def _safe_filename(value: str) -> str:
        filename = PurePath(str(value or "").replace("\\", "/").replace("\x00", "")).name.strip()
        if not filename:
            raise ContentServiceError("INVALID_INPUT", "INVALID_FILENAME")
        return filename[:255]

    @staticmethod
    def _display_name(value: str) -> str:
        name = str(value or "").strip()
        if not name or len(name) > 200:
            raise ContentServiceError("INVALID_INPUT", "INVALID_DISPLAY_NAME")
        return name

    @staticmethod
    def _tags(values) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, (list, tuple)):
            raise ContentServiceError("INVALID_INPUT", "INVALID_TAGS")
        result = []
        seen = set()
        for value in values:
            tag = str(value).strip()
            key = tag.casefold()
            if not tag or len(tag) > 40 or key in seen:
                continue
            seen.add(key)
            result.append(tag)
            if len(result) >= 20:
                break
        return result

    @staticmethod
    def _url(value: str) -> str:
        url = str(value or "").strip()
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise ContentServiceError("INVALID_INPUT", "INVALID_URL") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ContentServiceError("INVALID_INPUT", "INVALID_URL")
        return url

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        import json

        return {
            "id": row["id"],
            "source_kind": row["source_kind"],
            "display_name": row["display_name"],
            "description": row.get("description"),
            "tags": json.loads(row.get("tags_json") or "[]"),
            "original_filename": row.get("original_filename"),
            "content_type": row.get("content_type"),
            "size_bytes": row.get("size_bytes"),
            "duration_seconds": row.get("duration_seconds"),
            "status": row["status"],
            "source_summary": (
                redact_url(row["source_value"])
                if row["source_kind"] == "external_url" and row["source_value"]
                else "Managed file"
            ),
            "reference_count": int(row.get("reference_count", 0)),
            "last_used_at": row.get("last_used_at"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def create_external_url(
        self,
        url: str,
        *,
        display_name: str,
        description: str | None = None,
        tags=None,
    ) -> dict[str, Any]:
        import json

        row = self.repository.create_media_asset(
            {
                "id": self.id_factory(),
                "source_kind": "external_url",
                "display_name": self._display_name(display_name),
                "description": str(description).strip()[:1000] if description else None,
                "tags_json": json.dumps(self._tags(tags), ensure_ascii=False),
                "source_value": self._url(url),
            }
        )
        return self._public(row)

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        row = self.repository.get_media_asset(str(asset_id))
        if row is None or row["status"] == "deleted":
            raise ContentServiceError("NOT_FOUND", "ASSET_NOT_FOUND", {"asset_id": asset_id})
        return self._public(row)

    def resolve_source(self, asset_id: str) -> str:
        row = self.repository.get_media_asset(str(asset_id))
        if row is None:
            raise ContentServiceError("NOT_FOUND", "ASSET_NOT_FOUND", {"asset_id": asset_id})
        if row["status"] != "available" or not row["source_value"]:
            raise ContentServiceError("UNAVAILABLE", "ASSET_UNAVAILABLE", {"asset_id": asset_id})
        if row["source_kind"] == "managed_file":
            path = self.directory / row["source_value"]
            if not path.is_file():
                self.repository.update_media_asset(asset_id, {"status": "unavailable"})
                raise ContentServiceError("UNAVAILABLE", "ASSET_FILE_MISSING", {"asset_id": asset_id})
            return str(path)
        return row["source_value"]

    def resolve_managed_file(self, asset_id: str) -> tuple[Path, str]:
        row = self.repository.get_media_asset(str(asset_id))
        if row is None or row["status"] == "deleted":
            raise ContentServiceError("NOT_FOUND", "ASSET_NOT_FOUND", {"asset_id": asset_id})
        if row["source_kind"] != "managed_file":
            raise ContentServiceError("INVALID_INPUT", "ASSET_NOT_MANAGED_FILE")
        source = self.resolve_source(asset_id)
        return Path(source), row.get("content_type") or "application/octet-stream"

    def update_asset(
        self,
        asset_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        tags=None,
        external_url: str | None = None,
    ) -> dict[str, Any]:
        import json

        row = self.repository.get_media_asset(str(asset_id))
        if row is None or row["status"] == "deleted":
            raise ContentServiceError("NOT_FOUND", "ASSET_NOT_FOUND", {"asset_id": asset_id})
        values: dict[str, Any] = {}
        if display_name is not None:
            values["display_name"] = self._display_name(display_name)
        values["description"] = str(description).strip()[:1000] if description else None
        if tags is not None:
            values["tags_json"] = json.dumps(self._tags(tags), ensure_ascii=False)
        if external_url is not None:
            if row["source_kind"] != "external_url":
                raise ContentServiceError("INVALID_INPUT", "FILE_SOURCE_IMMUTABLE")
            values["source_value"] = self._url(external_url)
            values["status"] = "available"
        return self._public(self.repository.update_media_asset(asset_id, values))

    def list_assets(self, **filters) -> dict[str, Any]:
        result = self.repository.list_media_assets(**filters)
        return {"items": [self._public(row) for row in result["items"]], "total": result["total"]}

    def begin_upload(
        self,
        filename: str,
        content_type: str,
        size_bytes: int,
        *,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        self._expire_uploads()
        if isinstance(size_bytes, bool):
            raise ContentServiceError("INVALID_INPUT", "INVALID_FILE_SIZE")
        try:
            size = int(size_bytes)
        except (TypeError, ValueError) as exc:
            raise ContentServiceError("INVALID_INPUT", "INVALID_FILE_SIZE") from exc
        if size <= 0 or size > self.max_bytes:
            raise ContentServiceError("INVALID_INPUT", "INVALID_FILE_SIZE")
        safe_name = self._safe_filename(filename)
        upload_id = self.id_factory()
        self._uploads[upload_id] = PendingMediaUpload(
            id=upload_id,
            filename=safe_name,
            content_type=str(content_type or "application/octet-stream")[:120],
            size_bytes=size,
            display_name=self._display_name(display_name or safe_name),
            expires_at=self.clock() + self.upload_ttl,
        )
        return {
            "upload_id": upload_id,
            "upload_path": f"/api/v1/media/uploads/{upload_id}",
            "expires_in": int(self.upload_ttl),
            "max_bytes": self.max_bytes,
        }

    def _expire_uploads(self) -> None:
        now = self.clock()
        expired = [key for key, item in self._uploads.items() if item.expires_at <= now]
        for upload_id in expired:
            self._uploads.pop(upload_id, None)
            (self.upload_directory / f"{upload_id}.part").unlink(missing_ok=True)

    @staticmethod
    def _detect_format(header: bytes) -> str | None:
        if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
            return "wav"
        if header.startswith(b"fLaC"):
            return "flac"
        if header.startswith(b"OggS"):
            return "ogg"
        if header.startswith(b"ID3"):
            return "mp3"
        if len(header) >= 12 and header[4:8] == b"ftyp":
            return "m4a"
        if len(header) > 1 and header[0] == 0xFF and header[1] & 0xF6 == 0xF0:
            return "aac"
        if len(header) > 1 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0:
            return "mp3"
        if header.startswith(b"\x30\x26\xb2\x75"):
            return "wma"
        return None

    @staticmethod
    def _duration(path: Path, format_name: str) -> float | None:
        if format_name != "wav":
            return None
        try:
            with wave.open(str(path), "rb") as audio:
                return audio.getnframes() / float(audio.getframerate())
        except (wave.Error, OSError, ZeroDivisionError):
            return None

    async def accept_upload(self, upload_id: str, chunks: AsyncIterable[bytes]) -> dict[str, Any]:
        self._expire_uploads()
        upload = self._uploads.pop(str(upload_id), None)
        if upload is None:
            raise ContentServiceError("NOT_FOUND", "UPLOAD_NOT_FOUND")
        part = self.upload_directory / f"{upload.id}.part"
        digest = hashlib.sha256()
        written = 0
        header = bytearray()
        try:
            with part.open("xb") as output:
                async for chunk in chunks:
                    payload = bytes(chunk)
                    written += len(payload)
                    if written > upload.size_bytes or written > self.max_bytes:
                        raise ContentServiceError("INVALID_INPUT", "UPLOAD_SIZE_MISMATCH")
                    digest.update(payload)
                    if len(header) < 32:
                        header.extend(payload[: 32 - len(header)])
                    output.write(payload)
            if written != upload.size_bytes:
                raise ContentServiceError("INVALID_INPUT", "UPLOAD_SIZE_MISMATCH")
            format_name = self._detect_format(bytes(header))
            if format_name is None:
                raise ContentServiceError("INVALID_INPUT", "UNSUPPORTED_AUDIO")
            content_hash = digest.hexdigest()
            existing = self.repository.find_media_asset_by_hash(content_hash)
            blob = self.blob_directory / content_hash
            if existing is not None and existing["status"] != "deleted":
                part.unlink(missing_ok=True)
                return {"asset": self._public(existing), "deduplicated": True}
            if not blob.exists():
                part.replace(blob)
            else:
                part.unlink(missing_ok=True)
            try:
                row = self.repository.create_media_asset(
                    {
                        "id": self.id_factory(),
                        "source_kind": "managed_file",
                        "display_name": upload.display_name,
                        "original_filename": upload.filename,
                        "content_type": self._CONTENT_TYPES[format_name],
                        "size_bytes": written,
                        "duration_seconds": self._duration(blob, format_name),
                        "content_hash": content_hash,
                        "source_value": f"blobs/{content_hash}",
                    }
                )
            except Exception:
                if existing is None:
                    blob.unlink(missing_ok=True)
                raise
            return {"asset": self._public(row), "deduplicated": False}
        finally:
            part.unlink(missing_ok=True)

    def delete_asset(self, asset_id: str) -> dict[str, Any]:
        row = self.repository.get_media_asset(str(asset_id))
        if row is None or row["status"] == "deleted":
            raise ContentServiceError("NOT_FOUND", "ASSET_NOT_FOUND", {"asset_id": asset_id})
        references = self.repository.media_asset_references(asset_id)
        if references["playlist_items"] or references["active_sessions"]:
            raise ContentServiceError("CONFLICT", "ASSET_REFERENCED", references)
        if row["source_kind"] == "managed_file" and row["source_value"]:
            (self.directory / row["source_value"]).unlink(missing_ok=True)
        return self._public(self.repository.mark_media_asset_deleted(asset_id))
