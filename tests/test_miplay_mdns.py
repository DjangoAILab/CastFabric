import base64
import socket
import struct
import uuid

from miair.miplay.mdns import (
    MIPLAY_SERVICE_TYPE,
    MiPlayIdentity,
    decode_app_data,
    device_from_service_info,
)


def test_identity_builds_parseable_distinct_miplay_service():
    identity = MiPlayIdentity(
        address="192.168.31.9",
        friendly_name="OpenXiaoCast Test",
        instance="openxiaocast-test",
        host="openxiaocast-test",
        device_id=uuid.UUID("7e6d22d5-5cb9-4e3c-a95f-110fd8f53d42"),
        control_port=18899,
    )

    info = identity.service_info()
    assert info.type == MIPLAY_SERVICE_TYPE
    assert info.name == f"openxiaocast-test.{MIPLAY_SERVICE_TYPE}"
    assert info.port == 56666
    assert info.parsed_addresses() == ["192.168.31.9"]

    device = device_from_service_info(info)
    assert device.friendly_name == "OpenXiaoCast Test"
    assert device.address == "192.168.31.9"
    assert device.control_port == 18899
    assert device.device_id == identity.device_id
    assert device.supports_audio is True
    assert device.security_mode == 2


def test_app_data_container_carries_app_five_control_port_and_uuid():
    identity = MiPlayIdentity(
        address="127.0.0.1",
        device_id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        control_port=8899,
    )
    info = identity.service_info()
    properties = {
        key.decode(): value.decode() for key, value in info.properties.items()
    }
    payload = decode_app_data(properties["appsData"])

    assert struct.unpack(">H", payload[:2])[0] == 1155
    assert struct.unpack(">H", payload[2:4])[0] == 8899
    assert b"11111111-2222-3333-4444-555555555555" in payload
    assert properties["apps"] == "[5]"
    assert properties["sec"] == "2"

