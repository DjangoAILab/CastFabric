"""Stable product identity and user-visible device naming helpers."""

from __future__ import annotations


PRODUCT_NAME = "CastFabric"
PRODUCT_SLUG = "castfabric"
PRODUCT_DESCRIPTION = "Open-source multi-protocol casting fabric for LAN audio devices"
LEGACY_PRODUCT_NAMES = frozenset({"MiAir", "OpenXiaoCast"})
MAX_DEVICE_PREFIX_LENGTH = 80


def normalize_device_prefix(value: str | None) -> str:
    """Return a bounded prefix, migrating empty and former project defaults."""
    prefix = str(value or "").strip()
    if not prefix or prefix in LEGACY_PRODUCT_NAMES:
        return PRODUCT_NAME
    return prefix[:MAX_DEVICE_PREFIX_LENGTH]


def format_device_name(prefix: str, target_name: str = "") -> str:
    """Build a compact advertised name without duplicating its prefix."""
    normalized_prefix = normalize_device_prefix(prefix)
    suffix = str(target_name or "").strip()
    if not suffix or suffix == normalized_prefix:
        return normalized_prefix
    if suffix.startswith((f"{normalized_prefix} · ", f"{normalized_prefix} - ")):
        return suffix
    return f"{normalized_prefix} · {suffix}"

