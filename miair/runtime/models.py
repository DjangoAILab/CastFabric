"""Stable, explicitly serialized runtime snapshots used by API v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class _ValueEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class IngressProtocol(_ValueEnum):
    DLNA = "dlna"
    AIRPLAY = "airplay"
    MIPLAY = "miplay"
    MCP = "mcp"


RECEIVER_PROTOCOLS = (
    IngressProtocol.DLNA,
    IngressProtocol.AIRPLAY,
    IngressProtocol.MIPLAY,
)


class IngressState(_ValueEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    ACTIVE = "active"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SessionState(_ValueEnum):
    STARTING = "starting"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"


class EventOutcome(_ValueEnum):
    INFO = "info"
    SUCCESS = "success"
    FAILED = "failed"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class OutputTargetSnapshot:
    id: str
    kind: str
    name: str
    receiver_alias: str
    location_host: str
    configured: bool
    enabled: bool
    online: bool | None = None
    observed_at: datetime | None = None
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "receiver_alias": self.receiver_alias,
            "location_host": self.location_host,
            "configured": self.configured,
            "enabled": self.enabled,
            "online": self.online,
            "observed_at": _iso(self.observed_at),
            "capabilities": list(self.capabilities),
        }


@dataclass(frozen=True)
class IngressSnapshot:
    protocol: IngressProtocol
    state: IngressState
    port: int | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "port": self.port,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class ReceiverSuiteSnapshot:
    target: OutputTargetSnapshot
    health: str
    ingress: tuple[IngressSnapshot, ...] = ()
    current_session_id: str | None = None
    last_activity_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_dict(),
            "health": self.health,
            "ingress": {
                item.protocol.value: item.to_dict() for item in self.ingress
            },
            "current_session_id": self.current_session_id,
            "last_activity_at": _iso(self.last_activity_at),
        }


@dataclass(frozen=True)
class SessionSourceSnapshot:
    device_name: str | None = None
    provenance: str | None = None
    confidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_name": self.device_name,
            "provenance": self.provenance,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class MediaSessionSnapshot:
    id: str
    target_id: str
    protocol: IngressProtocol
    state: SessionState
    source: SessionSourceSnapshot = field(default_factory=SessionSourceSnapshot)
    media_format: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_id": self.target_id,
            "protocol": self.protocol.value,
            "state": self.state.value,
            "source": self.source.to_dict(),
            "media": {"format": self.media_format},
            "started_at": _iso(self.started_at),
            "ended_at": _iso(self.ended_at),
        }


@dataclass(frozen=True)
class ActivityEventSnapshot:
    id: str
    occurred_at: datetime
    target_id: str
    session_id: str | None
    protocol: IngressProtocol | None
    type: str
    outcome: EventOutcome
    summary_key: str
    reason_code: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "occurred_at": _iso(self.occurred_at),
            "target_id": self.target_id,
            "session_id": self.session_id,
            "protocol": self.protocol.value if self.protocol else None,
            "type": self.type,
            "outcome": self.outcome.value,
            "summary_key": self.summary_key,
            "reason_code": self.reason_code,
            "details": dict(self.details),
        }
