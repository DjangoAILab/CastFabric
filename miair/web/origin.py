"""Resolve control-plane and speaker-facing origins without mixing them."""

from __future__ import annotations

import ipaddress

from aiohttp import web


def request_public_origin(request: web.Request) -> str:
    """Return the origin visible to an HTTP client behind a TLS proxy."""

    scheme = request.scheme
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
    if forwarded_proto:
        candidate = forwarded_proto.split(",", 1)[0].strip().lower()
        if candidate in {"http", "https"}:
            scheme = candidate
    return f"{scheme}://{request.host}"


def speaker_media_origin(config) -> str:
    """Return the direct LAN HTTP origin that a DLNA renderer can fetch."""

    host = str(config.hostname).strip()
    try:
        if ipaddress.ip_address(host).version == 6:
            host = f"[{host}]"
    except ValueError:
        pass
    return f"http://{host}:{int(config.web_port)}"
