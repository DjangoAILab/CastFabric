"""Privacy projections shared by events, API responses and diagnostics."""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


_ALLOWED_EVENT_DETAILS = {
    "client_address",
    "control_action",
    "decoder_stage",
    "media_format",
    "output_adapter",
    "reason",
    "stream_url",
    "transport_state",
    "volume_percent",
}
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_MAX_DETAIL_TEXT = 256


def project_location_host(location: str) -> str:
    """Return only a valid description URL host for the local target registry."""
    try:
        parsed = urlsplit(str(location or ""))
        return parsed.hostname or "" if parsed.scheme in {"http", "https"} else ""
    except (TypeError, ValueError):
        return ""


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip("[]"))
        return True
    except ValueError:
        return False


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return _redact_text(value)
        host = "<local-address>" if _is_ip(parsed.hostname) else parsed.hostname
        netloc = host
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except (TypeError, ValueError):
        return "<redacted>"


def _redact_text(value: str) -> str:
    text = _IPV4_RE.sub("<local-address>", value)
    return text[:_MAX_DETAIL_TEXT]


def _redact_value(key: str, value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if key == "stream_url":
        return _redact_url(text)
    if key == "client_address" and _is_ip(text):
        return "<local-address>"
    return _redact_text(text)


def redact_event_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy only registered event fields and redact every copied value."""
    if not details:
        return {}
    return {
        key: _redact_value(key, value)
        for key, value in details.items()
        if key in _ALLOWED_EVENT_DETAILS
    }
