from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from miair.app import CastFabric
from miair.config import Config
from miair.dlna.client import DiscoveredDLNATarget
from miair.targets import OutputTargetConfig
from miair.runtime.models import IngressProtocol, IngressState


@pytest.mark.asyncio
async def test_generic_dlna_target_starts_ingress_without_xiaomi_login(tmp_path):
    target = OutputTargetConfig(
        id="uuid:renderer",
        name="Living Room",
        location="http://192.0.2.10/device.xml",
        udn="uuid:renderer",
    )
    config = Config(
        hostname="127.0.0.1",
        conf_path=str(tmp_path),
        cookie="userId=legacy; passToken=stale",
        enable_miplay=False,
        targets={target.id: target},
        default_target_id=target.id,
    )
    app = CastFabric(config)
    app.auth.login = AsyncMock(return_value=False)
    local_client = SimpleNamespace(location=target.location)

    with (
        patch(
            "miair.speaker.LocalDLNAClient.connect",
            AsyncMock(return_value=local_client),
        ),
        patch("miair.app.SSDPServer") as ssdp_cls,
        patch("miair.app.DeviceServer") as device_cls,
        patch.object(app, "_start_airplay_for_speakers", AsyncMock()) as airplay,
    ):
        ssdp_cls.return_value.start = AsyncMock()
        device_cls.return_value.start = AsyncMock()
        await app._start_dlna_services()

    app.auth.login.assert_not_awaited()
    airplay.assert_awaited_once()
    assert app.dlna_running
    assert "uuid:renderer" in app.speaker_manager.controllers
    controller = app.speaker_manager.controllers["uuid:renderer"]
    assert controller.local_dlna is local_client
    assert controller.auth is None
    assert config.enable_xiaomi_extension is False
    assert len(app.renderers) == 1
    assert next(iter(app.renderers.values())).friendly_name == (
        "CastFabric · Living Room"
    )
    suite = app.suite_registry.get(target.id)
    assert suite is not None
    assert suite.controller is controller
    assert suite.get_ingress(IngressProtocol.DLNA).state is IngressState.READY


@pytest.mark.asyncio
async def test_offline_generic_target_remains_advertised(tmp_path):
    target = OutputTargetConfig(
        id="uuid:offline",
        name="Offline Speaker",
        location="http://192.0.2.11/device.xml",
        udn="uuid:offline",
    )
    config = Config(
        hostname="127.0.0.1",
        conf_path=str(tmp_path),
        enable_miplay=False,
        targets={target.id: target},
        default_target_id=target.id,
    )
    app = CastFabric(config)

    with (
        patch(
            "miair.speaker.LocalDLNAClient.connect",
            AsyncMock(return_value=None),
        ),
        patch("miair.app.SSDPServer") as ssdp_cls,
        patch("miair.app.DeviceServer") as device_cls,
        patch.object(app, "_start_airplay_for_speakers", AsyncMock()),
    ):
        ssdp_cls.return_value.start = AsyncMock()
        device_cls.return_value.start = AsyncMock()
        await app._start_dlna_services()

    assert app.dlna_running
    assert len(app.renderers) == 1
    assert not app.has_local_speaker_control()
    assert app.suite_registry.get(target.id).snapshot().target.online is None


@pytest.mark.asyncio
async def test_discovery_scan_updates_live_client_after_renderer_port_changes(tmp_path):
    target = OutputTargetConfig(
        id="uuid:renderer",
        name="Living Room",
        location="http://192.0.2.10:1269/",
        udn="uuid:renderer",
    )
    config = Config(
        hostname="192.0.2.20",
        conf_path=str(tmp_path),
        targets={target.id: target},
        default_target_id=target.id,
    )
    app = CastFabric(config)
    client = SimpleNamespace(update_endpoint=AsyncMock())
    controller = SimpleNamespace(local_dlna=client)
    app.speaker_manager.get_controller_for_target = Mock(return_value=controller)
    services = {
        "urn:schemas-upnp-org:service:AVTransport:1": (
            "http://192.0.2.10:2026/av/control.xml"
        )
    }
    app.discovery_registry._discover = AsyncMock(
        return_value=[
            DiscoveredDLNATarget(
                id=target.id,
                name=target.name,
                location="http://192.0.2.10:2026/",
                services=services,
            )
        ]
    )

    await app.scan_output_targets()

    assert target.location == "http://192.0.2.10:2026/"
    client.update_endpoint.assert_awaited_once_with(
        "http://192.0.2.10:2026/",
        services,
    )
