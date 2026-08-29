from miair.const import AVTRANSPORT_URN, RENDERING_CONTROL_URN
from miair.dlna.client import (
    _normalize_udn,
    _parse_device_description,
    _parse_ssdp_target,
)


DESCRIPTION = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>Living Room Speaker</friendlyName>
    <UDN>uuid:ABC-123</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <controlURL>/upnp/av/control</controlURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
        <controlURL>render/control</controlURL>
      </service>
    </serviceList>
  </device>
</root>
"""


def test_udn_normalization_is_stable_and_case_insensitive():
    assert _normalize_udn("uuid:ABC-123::urn:device") == "uuid:abc-123"
    assert _normalize_udn("ABC-123") == "uuid:abc-123"


def test_ssdp_target_requires_renderer_usn_and_location():
    target = _parse_ssdp_target(
        {
            "usn": "uuid:ABC-123::urn:schemas-upnp-org:device:MediaRenderer:1",
            "st": "urn:schemas-upnp-org:device:MediaRenderer:1",
            "location": "http://192.0.2.10:1958/device.xml",
        }
    )

    assert target == (
        "uuid:abc-123",
        "http://192.0.2.10:1958/device.xml",
    )
    assert _parse_ssdp_target({"usn": "uuid:x", "location": ""}) is None


def test_device_description_extracts_name_udn_and_absolute_services():
    target = _parse_device_description(
        DESCRIPTION, "http://192.0.2.10:1958/device/description.xml"
    )

    assert target.id == "uuid:abc-123"
    assert target.name == "Living Room Speaker"
    assert target.location == "http://192.0.2.10:1958/device/description.xml"
    assert target.services[AVTRANSPORT_URN] == "http://192.0.2.10:1958/upnp/av/control"
    assert target.services[RENDERING_CONTROL_URN] == (
        "http://192.0.2.10:1958/device/render/control"
    )

