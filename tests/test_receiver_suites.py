from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from miair.airplay.speaker_airplay import AirPlayManager
from miair.app import CastFabric
from miair.config import Config
from miair.dlna.device_server import DeviceServer
from miair.dlna.ssdp import SSDPServer
from miair.runtime.models import IngressProtocol, IngressState
from miair.runtime.suites import ReceiverSuiteRegistry, SuiteLifecycleError
from miair.targets import OutputTargetConfig


def _target(target_id: str, name: str, *, enabled: bool = True):
    return OutputTargetConfig(
        id=target_id,
        name=name,
        location="http://192.0.2.20/device.xml",
        enabled=enabled,
    )


def test_registry_keeps_stable_target_controller_mapping_and_two_snapshots():
    registry = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    living = _target("uuid:living", "Living Room")
    bedroom = _target("uuid:bedroom", "Bedroom")
    living_controller = SimpleNamespace(local_dlna=object())
    bedroom_controller = SimpleNamespace(local_dlna=None)

    registry.register(living, "legacy-living", living_controller)
    registry.register(bedroom, "uuid:bedroom", bedroom_controller)
    registry.set_ingress(
        living.id,
        IngressProtocol.DLNA,
        IngressState.READY,
        handle=object(),
        port=8200,
    )
    registry.set_ingress(
        bedroom.id,
        IngressProtocol.AIRPLAY,
        IngressState.UNAVAILABLE,
        error_code="AIRPLAY_START_FAILED",
    )

    assert registry.get_by_controller_id("legacy-living").target.id == living.id
    assert registry.get(living.id).controller is living_controller
    snapshots = {item.target.id: item for item in registry.snapshots()}
    assert set(snapshots) == {living.id, bedroom.id}
    assert snapshots[living.id].target.receiver_alias == "CastFabric · Living Room"
    assert snapshots[living.id].target.online is None
    assert snapshots[living.id].health == "healthy"
    assert snapshots[bedroom.id].health == "degraded"
    assert snapshots[bedroom.id].ingress[0].error_code == "AIRPLAY_START_FAILED"


@pytest.mark.asyncio
async def test_disable_failure_restores_enabled_state_and_original_suite():
    registry = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    target = _target("uuid:living", "Living Room")
    suite = registry.register(target, target.id, SimpleNamespace())
    renderer = object()
    registry.set_ingress(
        target.id,
        IngressProtocol.DLNA,
        IngressState.READY,
        handle=renderer,
        port=8200,
    )
    stop = AsyncMock(side_effect=RuntimeError("injected stop failure"))
    start = AsyncMock()

    with pytest.raises(SuiteLifecycleError) as exc:
        await registry.set_enabled(target.id, False, start=start, stop=stop)

    assert exc.value.code == "SUITE_DISABLE_FAILED"
    assert target.enabled is True
    assert registry.get(target.id) is suite
    assert registry.get(target.id).get_ingress(IngressProtocol.DLNA).handle is renderer
    start.assert_awaited_once_with(suite)


@pytest.mark.asyncio
async def test_enable_failure_rolls_back_to_disabled_suite():
    registry = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    target = _target("uuid:living", "Living Room", enabled=False)
    suite = registry.register(target, target.id, SimpleNamespace())
    start = AsyncMock(side_effect=OSError("injected bind failure"))
    stop = AsyncMock()

    with pytest.raises(SuiteLifecycleError) as exc:
        await registry.set_enabled(target.id, True, start=start, stop=stop)

    assert exc.value.code == "SUITE_ENABLE_FAILED"
    assert target.enabled is False
    assert registry.get(target.id) is suite
    stop.assert_awaited_once_with(suite)


def test_stopped_ingress_can_explicitly_release_its_runtime_handle():
    registry = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    target = _target("uuid:living", "Living Room")
    registry.register(target, target.id, SimpleNamespace())
    registry.set_ingress(
        target.id,
        IngressProtocol.DLNA,
        IngressState.READY,
        handle=object(),
        port=8200,
    )

    runtime = registry.set_ingress(
        target.id,
        IngressProtocol.DLNA,
        IngressState.STOPPED,
        handle=None,
    )

    assert runtime.handle is None
    assert runtime.port == 8200


@pytest.mark.asyncio
async def test_shared_dlna_servers_unregister_only_requested_renderer():
    ssdp = SSDPServer("127.0.0.1", 8200)
    ssdp._transport = Mock()
    ssdp.register_renderer("living", "Living")
    ssdp.register_renderer("bedroom", "Bedroom")

    renderer = SimpleNamespace(udn="living")
    other = SimpleNamespace(udn="bedroom")
    device = DeviceServer("127.0.0.1", 8200)
    device.register_renderer(renderer)
    device.register_renderer(other)
    living_events = device.event_managers["living"]
    living_events.stop = AsyncMock()

    assert await ssdp.unregister_renderer("living") is True
    assert await device.unregister_renderer("living") is renderer

    assert set(ssdp.renderers) == {"bedroom"}
    assert set(device.renderers) == {"bedroom"}
    assert "living" not in device.event_managers
    living_events.stop.assert_awaited_once()
    assert ssdp._transport.sendto.call_count == len(ssdp._get_search_targets("living"))


@pytest.mark.asyncio
async def test_airplay_manager_can_stop_one_speaker_without_closing_shared_zeroconf():
    manager = AirPlayManager("127.0.0.1")
    living = SimpleNamespace(stop=AsyncMock())
    bedroom = SimpleNamespace(stop=AsyncMock())
    manager.speaker_airplays = {"living": living, "bedroom": bedroom}
    manager._shared_zeroconf = Mock()

    assert await manager.stop_for_speaker("living") is living

    living.stop.assert_awaited_once()
    bedroom.stop.assert_not_awaited()
    assert set(manager.speaker_airplays) == {"bedroom"}
    manager._shared_zeroconf.close.assert_not_called()


@pytest.mark.asyncio
async def test_one_airplay_start_failure_keeps_other_receiver_and_both_dlna_suites():
    manager = AirPlayManager("127.0.0.1")
    manager._shared_zeroconf = Mock()
    controllers = {
        "living": SimpleNamespace(speaker=SimpleNamespace(get_dlna_name=lambda: "Living")),
        "bedroom": SimpleNamespace(speaker=SimpleNamespace(get_dlna_name=lambda: "Bedroom")),
    }
    starts = [RuntimeError("injected AirPlay failure"), None]

    with patch("miair.airplay.speaker_airplay.SpeakerAirPlay") as wrapper_cls:
        first = SimpleNamespace(start=AsyncMock(side_effect=starts[0]))
        second = SimpleNamespace(start=AsyncMock(return_value=starts[1]))
        wrapper_cls.side_effect = [first, second]
        await manager.start_for_speakers(controllers)

    registry = ReceiverSuiteRegistry(device_name_prefix="CastFabric")
    for target_id, controller in controllers.items():
        registry.register(_target(f"uuid:{target_id}", target_id), target_id, controller)
        registry.set_ingress(
            f"uuid:{target_id}",
            IngressProtocol.DLNA,
            IngressState.READY,
            handle=object(),
            port=8200,
        )
    registry.set_ingress(
        "uuid:living",
        IngressProtocol.AIRPLAY,
        IngressState.UNAVAILABLE,
        error_code="AIRPLAY_START_FAILED",
    )
    registry.set_ingress(
        "uuid:bedroom",
        IngressProtocol.AIRPLAY,
        IngressState.READY,
        handle=manager.speaker_airplays["bedroom"],
    )

    assert set(manager.speaker_airplays) == {"bedroom"}
    assert all(
        registry.get(target_id).get_ingress(IngressProtocol.DLNA).state
        is IngressState.READY
        for target_id in ("uuid:living", "uuid:bedroom")
    )


@pytest.mark.asyncio
async def test_compensation_start_reuses_a_dlna_renderer_that_is_still_live(tmp_path):
    target = _target("uuid:living", "Living Room")
    app = CastFabric(
        Config(
            hostname="127.0.0.1",
            conf_path=str(tmp_path),
            targets={target.id: target},
        )
    )
    renderer = SimpleNamespace(udn="virtual-living")
    controller = SimpleNamespace()
    suite = app.suite_registry.register(target, target.id, controller)
    app.suite_registry.set_ingress(
        target.id,
        IngressProtocol.DLNA,
        IngressState.READY,
        handle=renderer,
        port=8200,
    )
    app.renderers[renderer.udn] = renderer
    app.ssdp_server = SimpleNamespace(renderers={renderer.udn: "Living"})
    app.device_server = SimpleNamespace(renderers={renderer.udn: renderer})
    wrapper = SimpleNamespace(airplay_server=SimpleNamespace(rtsp_port=7000))
    app.airplay_manager = SimpleNamespace(
        start_for_speaker=AsyncMock(return_value=wrapper)
    )

    with patch.object(
        app,
        "_register_dlna_renderer",
        AsyncMock(),
    ) as register:
        await app._start_receiver_suite(suite)

    register.assert_not_awaited()
    app.airplay_manager.start_for_speaker.assert_awaited_once_with(
        target.id,
        controller,
    )
