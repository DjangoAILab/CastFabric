"""Minimal local UPnP MediaRenderer client for Xiaomi speaker fallback."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import socket
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

import aiohttp

from miair.const import AVTRANSPORT_URN, RENDERING_CONTROL_URN, SSDP_ADDR, SSDP_PORT

log = logging.getLogger("miair")


@dataclass(frozen=True)
class DiscoveredDLNATarget:
    id: str
    name: str
    location: str
    services: dict[str, str]


def _normalize_udn(value: str) -> str:
    raw = str(value or "").strip().lower().split("::", 1)[0]
    if not raw:
        return ""
    return raw if raw.startswith("uuid:") else f"uuid:{raw}"


def _parse_ssdp_target(headers: dict[str, str]) -> tuple[str, str] | None:
    location = headers.get("location", "").strip()
    udn = _normalize_udn(headers.get("usn", ""))
    if not location or not udn:
        return None
    return udn, location


def _parse_device_description(
    payload: bytes, location: str
) -> DiscoveredDLNATarget:
    root = ET.fromstring(payload)
    name = ""
    udn = ""
    services = {}
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "friendlyName" and not name:
            name = (node.text or "").strip()
        elif tag == "UDN" and not udn:
            udn = _normalize_udn(node.text or "")
        elif tag == "service":
            values = {
                child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
                for child in node
            }
            service_type = values.get("serviceType", "")
            control_url = values.get("controlURL", "")
            if service_type and control_url:
                services[service_type] = urljoin(location, control_url)
    if not udn:
        raise ValueError("DLNA device description has no UDN")
    return DiscoveredDLNATarget(
        id=udn,
        name=name or udn,
        location=location,
        services=services,
    )


class LocalDLNAClient:
    """Discover and control a physical DLNA MediaRenderer on the LAN."""

    def __init__(
        self,
        location: str,
        services: dict[str, str],
        *,
        device_id: str = "",
        interface_ip: str = "",
        endpoint_changed: Callable[[str], None] | None = None,
    ):
        self.location = location
        self.services = services
        self.device_id = _normalize_udn(device_id)
        self.interface_ip = str(interface_ip or "")
        self._endpoint_changed = endpoint_changed
        self._refresh_lock = asyncio.Lock()

    def set_endpoint_changed_callback(
        self,
        callback: Callable[[str], None] | None,
    ) -> None:
        self._endpoint_changed = callback

    def _apply_endpoint(
        self,
        location: str,
        services: dict[str, str],
    ) -> bool:
        previous_location = self.location
        changed = location != self.location or services != self.services
        self.location = location
        self.services = dict(services)
        if self._endpoint_changed and location != previous_location:
            try:
                self._endpoint_changed(location)
            except Exception as exc:
                # Persistence must never turn a recovered control path into a
                # playback failure.
                log.warning(
                    "保存实体 DLNA 新地址失败: %s",
                    type(exc).__name__,
                )
        return changed

    async def update_endpoint(
        self,
        location: str,
        services: dict[str, str],
    ) -> bool:
        """Apply a discovery observation without replacing active adapters."""
        async with self._refresh_lock:
            return self._apply_endpoint(location, services)

    @classmethod
    async def connect(
        cls,
        device_id: str,
        interface_ip: str,
        cached_location: str = "",
    ) -> "LocalDLNAClient | None":
        locations = []
        if cached_location:
            locations.append(cached_location)
        discovered = await cls._discover_location(device_id, interface_ip)
        if discovered and discovered not in locations:
            locations.append(discovered)

        for location in locations:
            try:
                services = await cls._load_services(location)
                if AVTRANSPORT_URN in services and RENDERING_CONTROL_URN in services:
                    return cls(
                        location,
                        services,
                        device_id=device_id,
                        interface_ip=interface_ip,
                    )
            except Exception as exc:
                log.debug("验证本地 DLNA 设备失败 %s: %s", location, type(exc).__name__)
        return None

    @classmethod
    async def discover(
        cls, interface_ip: str, timeout: float = 1.5
    ) -> list[DiscoveredDLNATarget]:
        """Discover every standards-compliant MediaRenderer on one interface."""
        locations = await cls._discover_locations(interface_ip, timeout)
        targets = []
        for expected_udn, location in locations.items():
            try:
                target = await cls._load_description(location)
            except Exception as exc:
                log.debug(
                    "读取 DLNA 设备描述失败 %s: %s",
                    location,
                    type(exc).__name__,
                )
                continue
            if target.id != expected_udn:
                log.debug(
                    "DLNA UDN 以设备描述为准: SSDP=%s description=%s",
                    expected_udn,
                    target.id,
                )
            if AVTRANSPORT_URN in target.services:
                targets.append(target)
        deduplicated = {target.id: target for target in targets}
        return sorted(deduplicated.values(), key=lambda item: item.name.lower())

    @staticmethod
    async def _discover_locations(
        interface_ip: str, timeout: float
    ) -> dict[str, str]:
        message = (
            "M-SEARCH * HTTP/1.1\r\n"
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 1\r\n"
            "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
        ).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setblocking(False)
        results = {}
        try:
            if interface_ip:
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(interface_ip),
                )
            loop = asyncio.get_running_loop()
            await loop.sock_sendto(sock, message, (SSDP_ADDR, SSDP_PORT))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data, _ = await asyncio.wait_for(
                        loop.sock_recvfrom(sock, 65535),
                        timeout=max(0.05, deadline - time.monotonic()),
                    )
                except asyncio.TimeoutError:
                    break
                parsed = _parse_ssdp_target(_parse_ssdp_headers(data))
                if parsed:
                    udn, location = parsed
                    results[udn] = location
        except (OSError, ValueError):
            pass
        finally:
            sock.close()
        return results

    @staticmethod
    async def _discover_location(
        device_id: str, interface_ip: str, timeout: float = 1.5
    ) -> str:
        normalized = device_id.lower().removeprefix("uuid:")
        message = (
            "M-SEARCH * HTTP/1.1\r\n"
            f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 1\r\n"
            "ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n"
        ).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setblocking(False)
        try:
            if interface_ip:
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(interface_ip),
                )
            loop = asyncio.get_running_loop()
            await loop.sock_sendto(sock, message, (SSDP_ADDR, SSDP_PORT))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data, _ = await asyncio.wait_for(
                        loop.sock_recvfrom(sock, 65535),
                        timeout=max(0.05, deadline - time.monotonic()),
                    )
                except asyncio.TimeoutError:
                    break
                headers = _parse_ssdp_headers(data)
                usn = headers.get("usn", "").lower()
                location = headers.get("location", "")
                if normalized and normalized in usn and location:
                    return location
        except (OSError, ValueError):
            pass
        finally:
            sock.close()
        return ""

    @staticmethod
    async def _load_services(location: str) -> dict[str, str]:
        return (await LocalDLNAClient._load_description(location)).services

    @staticmethod
    async def _load_description(location: str) -> DiscoveredDLNATarget:
        timeout = aiohttp.ClientTimeout(total=4, connect=2, sock_read=2)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(location) as response:
                response.raise_for_status()
                payload = await response.read()
        return _parse_device_description(payload, location)

    async def _soap_once(
        self,
        service_url: str,
        urn: str,
        action: str,
        arguments: dict,
    ) -> dict[str, str]:
        inner = "".join(
            f"<{key}>{html.escape(str(value), quote=True)}</{key}>"
            for key, value in arguments.items()
        )
        payload = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            f'<s:Body><u:{action} xmlns:u="{urn}">{inner}</u:{action}></s:Body>'
            "</s:Envelope>"
        ).encode()
        timeout = aiohttp.ClientTimeout(total=5, connect=2, sock_read=3)
        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{urn}#{action}"',
        }
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                service_url, data=payload, headers=headers
            ) as response:
                response.raise_for_status()
                raw = await response.read()
        root = ET.fromstring(raw)
        return {
            node.tag.rsplit("}", 1)[-1]: node.text or ""
            for node in root.iter()
            if len(node) == 0
        }

    async def _refresh_after_connection_failure(
        self,
        urn: str,
        failed_service_url: str,
    ) -> bool:
        """Atomically refresh a renderer whose reboot changed its HTTP port."""
        if not self.device_id or not self.interface_ip:
            return False
        async with self._refresh_lock:
            # Another concurrent command may already have refreshed the client.
            current_url = self.services.get(urn, "")
            if current_url and current_url != failed_service_url:
                return True
            location = await self._discover_location(
                self.device_id,
                self.interface_ip,
            )
            if not location:
                return False
            try:
                services = await self._load_services(location)
            except Exception as exc:
                log.warning(
                    "重新读取实体 DLNA 服务失败: %s",
                    type(exc).__name__,
                )
                return False
            if urn not in services:
                return False
            previous_location = self.location
            self._apply_endpoint(location, services)
            log.info(
                "实体 DLNA 控制地址已重新发现: %s -> %s",
                previous_location,
                location,
            )
            return True

    async def _soap(self, urn: str, action: str, arguments: dict) -> dict[str, str]:
        service_url = self.services[urn]
        try:
            return await self._soap_once(service_url, urn, action, arguments)
        except (aiohttp.ClientConnectionError, TimeoutError):
            if not await self._refresh_after_connection_failure(urn, service_url):
                raise
            log.info("实体 DLNA 连接恢复，重试 SOAP %s", action)
            return await self._soap_once(
                self.services[urn],
                urn,
                action,
                arguments,
            )

    async def play_url(self, url: str) -> bool:
        await self._soap(
            AVTRANSPORT_URN,
            "SetAVTransportURI",
            {"InstanceID": 0, "CurrentURI": url, "CurrentURIMetaData": ""},
        )
        await self._soap(
            AVTRANSPORT_URN, "Play", {"InstanceID": 0, "Speed": 1}
        )
        return True

    async def pause(self) -> bool:
        try:
            await self._soap(AVTRANSPORT_URN, "Pause", {"InstanceID": 0})
        except Exception:
            # Some Xiaomi renderers expose Pause in SCPD but only implement
            # Stop reliably. This matches the existing M01 cloud semantics.
            await self._soap(AVTRANSPORT_URN, "Stop", {"InstanceID": 0})
        return True

    async def resume(self) -> bool:
        await self._soap(AVTRANSPORT_URN, "Play", {"InstanceID": 0, "Speed": 1})
        return True

    async def stop(self) -> bool:
        await self._soap(AVTRANSPORT_URN, "Stop", {"InstanceID": 0})
        return True

    async def seek(self, position_seconds: int) -> bool:
        seconds = int(position_seconds)
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        await self._soap(
            AVTRANSPORT_URN,
            "Seek",
            {
                "InstanceID": 0,
                "Unit": "REL_TIME",
                "Target": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
            },
        )
        return True

    async def set_volume(self, volume: int) -> bool:
        await self._soap(
            RENDERING_CONTROL_URN,
            "SetVolume",
            {"InstanceID": 0, "Channel": "Master", "DesiredVolume": volume},
        )
        return True

    async def get_volume(self) -> int:
        result = await self._soap(
            RENDERING_CONTROL_URN,
            "GetVolume",
            {"InstanceID": 0, "Channel": "Master"},
        )
        return int(result.get("CurrentVolume", 0))

    async def get_status(self) -> dict:
        transport, volume, position, seek_supported = await asyncio.gather(
            self._soap(AVTRANSPORT_URN, "GetTransportInfo", {"InstanceID": 0}),
            self.get_volume(),
            self._get_position(),
            self._seek_supported(),
        )
        state = transport.get("CurrentTransportState", "STOPPED")
        status = {"PLAYING": 1, "PAUSED_PLAYBACK": 2}.get(state, 0)
        return {"status": status, "volume": volume, "seek_supported": seek_supported, **position}

    async def _seek_supported(self) -> bool:
        try:
            actions = await self._soap(
                AVTRANSPORT_URN, "GetCurrentTransportActions", {"InstanceID": 0}
            )
        except (aiohttp.ClientError, TimeoutError, ET.ParseError):
            return False
        return "Seek" in {value.strip() for value in actions.get("Actions", "").split(",")}

    async def _get_position(self) -> dict:
        # Position reporting is optional on renderers. Its absence must not
        # break transport controls or turn an unknown end into completion.
        try:
            result = await self._soap(
                AVTRANSPORT_URN, "GetPositionInfo", {"InstanceID": 0}
            )
        except (aiohttp.ClientError, TimeoutError, ET.ParseError):
            return {}
        position = {}
        for source, destination in (
            ("RelTime", "position_seconds"),
            ("TrackDuration", "duration_seconds"),
        ):
            value = _parse_transport_time(result.get(source, ""))
            if value is not None:
                position[destination] = value
        return position


def _parse_transport_time(value: str) -> float | None:
    """Parse UPnP H+:MM:SS[.fraction], leaving unsupported values unknown."""
    if not re.fullmatch(r"\d+:[0-5]\d:[0-5]\d(?:\.\d+)?", value):
        return None
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _parse_ssdp_headers(data: bytes) -> dict[str, str]:
    """Parse case-insensitive SSDP headers without trusting response content."""
    result = {}
    for line in data.decode("utf-8", "replace").split("\r\n")[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip().lower()] = value.strip()
    return result
