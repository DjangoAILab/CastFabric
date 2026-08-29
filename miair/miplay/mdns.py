"""MiPlay mDNS identity generation and discovery models."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field

from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, Zeroconf


MIPLAY_SERVICE_TYPE = "_mi-connect._udp.local."
MIPLAY_AUDIO_APP_ID = 5
MICONNECT_COAP_PORT = 56_666


def encode_app_data(device_id: uuid.UUID, control_port: int) -> str:
    if not 1 <= control_port <= 65535:
        raise ValueError("control port out of range")
    json_bytes = json.dumps(
        {"mico": {"device_id": str(device_id)}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    app_payload = bytearray(25 + len(json_bytes))
    struct.pack_into(">H", app_payload, 0, 1155)
    struct.pack_into(">H", app_payload, 2, control_port)
    digest = hashlib.sha256(device_id.bytes).digest()
    app_payload[4] = (digest[0] & 0xFC) | 0x02
    app_payload[5:10] = digest[1:6]
    app_payload[24] = 0
    app_payload[25:] = json_bytes
    if len(app_payload) > 255:
        raise ValueError("MiPlay app data exceeds one-byte container length")
    container = bytes([0x81, 0, len(app_payload)]) + bytes(app_payload)
    return base64.b64encode(container).decode("ascii")


def decode_app_data(value: str) -> bytes:
    try:
        container = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError("invalid MiPlay appsData base64") from exc
    if len(container) < 3 or container[0:2] != b"\x81\x00":
        raise ValueError("unsupported MiPlay appsData container")
    length = container[2]
    if len(container) != 3 + length:
        raise ValueError("MiPlay appsData length mismatch")
    return container[3:]


@dataclass(frozen=True, slots=True)
class MiPlayDevice:
    friendly_name: str
    instance_name: str
    address: str
    control_port: int
    device_id: uuid.UUID
    supports_audio: bool
    security_mode: int
    properties: dict[str, str]


@dataclass(frozen=True, slots=True)
class MiPlayIdentity:
    address: str
    friendly_name: str = "CastFabric"
    instance: str = "CastFabric"
    host: str = "openxiaocast"
    device_id: uuid.UUID = field(default_factory=uuid.uuid4)
    control_port: int = 8899

    def service_info(self) -> ServiceInfo:
        address = ipaddress.ip_address(self.address)
        if address.version != 4:
            raise ValueError("MiPlay identity requires IPv4")
        instance = self.instance.rstrip(".")
        host = self.host.rstrip(".")
        properties = {
            "name": self.friendly_name,
            "version": "65545",
            "apps": "[5]",
            "appsData": encode_app_data(self.device_id, self.control_port),
            "dev": "4",
            "sec": "2",
            "flags": "Ag==",
            "idHash": "T1hD",
        }
        return ServiceInfo(
            MIPLAY_SERVICE_TYPE,
            f"{instance}.{MIPLAY_SERVICE_TYPE}",
            addresses=[address.packed],
            port=MICONNECT_COAP_PORT,
            properties=properties,
            server=f"{host}.local.",
        )


def _decode_properties(info: ServiceInfo) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in info.properties.items():
        key_text = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
        value_text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        result[key_text] = value_text
    return result


def device_from_service_info(info: ServiceInfo) -> MiPlayDevice:
    properties = _decode_properties(info)
    addresses = info.parsed_addresses()
    if not addresses:
        raise ValueError("MiPlay service has no IPv4 address")
    apps = properties.get("apps", "")
    supports_audio = "5" in apps.strip("[]").split(",")
    app_payload = decode_app_data(properties["appsData"])
    if len(app_payload) < 25:
        raise ValueError("MiPlay app payload is truncated")
    control_port = struct.unpack(">H", app_payload[2:4])[0]
    json_offset = app_payload.find(b"{")
    if json_offset < 0:
        raise ValueError("MiPlay app payload has no identity JSON")
    identity = json.loads(app_payload[json_offset:].decode("utf-8"))
    device_id = uuid.UUID(identity["mico"]["device_id"])
    return MiPlayDevice(
        friendly_name=properties.get("name", info.name.split(".", 1)[0]),
        instance_name=info.name,
        address=addresses[0],
        control_port=control_port,
        device_id=device_id,
        supports_audio=supports_audio,
        security_mode=int(properties.get("sec", "0")),
        properties=properties,
    )


def scan_miplay(timeout: float = 3.0) -> list[MiPlayDevice]:
    """Browse MiPlay services for a bounded interval and return valid devices."""

    if timeout <= 0 or timeout > 60:
        raise ValueError("scan timeout must be between 0 and 60 seconds")
    devices: dict[str, MiPlayDevice] = {}
    lock = threading.Lock()
    zeroconf = Zeroconf(ip_version=IPVersion.V4Only)

    class Listener:
        def add_service(self, zc, service_type, name):
            self.update_service(zc, service_type, name)

        def update_service(self, zc, service_type, name):
            info = zc.get_service_info(service_type, name, timeout=1000)
            if info is None:
                return
            try:
                device = device_from_service_info(info)
            except (ValueError, KeyError, json.JSONDecodeError):
                return
            with lock:
                devices[name] = device

        def remove_service(self, zc, service_type, name):
            with lock:
                devices.pop(name, None)

    browser = ServiceBrowser(zeroconf, MIPLAY_SERVICE_TYPE, Listener())
    try:
        time.sleep(timeout)
    finally:
        browser.cancel()
        zeroconf.close()
    with lock:
        return sorted(devices.values(), key=lambda item: item.friendly_name)
