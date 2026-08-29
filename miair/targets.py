"""Persisted, vendor-neutral output target configuration."""

from __future__ import annotations

from dataclasses import dataclass


def normalize_target_id(value: str) -> str:
    raw = str(value or "").strip().lower().split("::", 1)[0]
    if not raw:
        return ""
    return raw if raw.startswith("uuid:") else f"uuid:{raw}"


@dataclass
class OutputTargetConfig:
    id: str
    kind: str = "dlna"
    name: str = ""
    location: str = ""
    udn: str = ""
    enabled: bool = True
    virtual_udn: str = ""
    legacy_did: str = ""

    def __post_init__(self):
        self.id = normalize_target_id(self.id) or str(self.id).strip()
        self.kind = str(self.kind or "dlna").strip().lower()
        self.name = str(self.name or self.id).strip()
        self.location = str(self.location or "").strip()
        self.udn = normalize_target_id(self.udn or self.id)
        self.enabled = bool(self.enabled)

