import pytest

from miair.config import Config
from miair.dlna.client import DiscoveredDLNATarget
from miair.targets import OutputTargetConfig
from miair.web.api import _apply_target_selection, _target_view


def discovered(target_id="uuid:new", name="New Speaker"):
    return DiscoveredDLNATarget(
        id=target_id,
        name=name,
        location="http://192.0.2.20/device.xml",
        services={},
    )


def test_target_view_keeps_offline_selection_and_adds_online_renderers():
    configured = OutputTargetConfig(
        id="uuid:old",
        name="Old Speaker",
        location="http://192.0.2.10/device.xml",
        enabled=True,
    )
    config = Config(
        hostname="127.0.0.1",
        targets={configured.id: configured},
        default_target_id=configured.id,
    )
    online = discovered()

    view = _target_view(config, {online.id: online})

    assert view[0] == {
        "id": "uuid:old",
        "kind": "dlna",
        "name": "Old Speaker",
        "location": "http://192.0.2.10/device.xml",
        "udn": "uuid:old",
        "selected": True,
        "default": True,
        "online": False,
    }
    assert view[1]["id"] == "uuid:new"
    assert view[1]["online"] is True
    assert view[1]["selected"] is False


def test_selection_can_add_only_an_ssdp_observed_target():
    config = Config(hostname="127.0.0.1")
    online = discovered()

    _apply_target_selection(config, [online.id], {online.id: online})

    assert config.default_target_id == online.id
    assert config.get_default_target().location == online.location

    with pytest.raises(ValueError, match="was not discovered"):
        _apply_target_selection(config, ["uuid:untrusted"], {})


def test_selection_disables_previous_target_and_honors_requested_default():
    first = OutputTargetConfig(id="uuid:first", name="First")
    second = OutputTargetConfig(id="uuid:second", name="Second")
    config = Config(
        hostname="127.0.0.1",
        targets={first.id: first, second.id: second},
        default_target_id=first.id,
    )

    _apply_target_selection(
        config,
        [second.id],
        {},
        default_target_id=second.id,
    )

    assert config.get_target(first.id).enabled is False
    assert config.get_target(second.id).enabled is True
    assert config.default_target_id == second.id

