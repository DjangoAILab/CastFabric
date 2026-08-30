import json

from miair.config import Config
from miair.targets import OutputTargetConfig


def test_generic_dlna_target_does_not_require_xiaomi_credentials():
    target = OutputTargetConfig(
        id="uuid:renderer",
        kind="dlna",
        name="Living Room",
        location="http://192.0.2.10/device.xml",
        udn="uuid:renderer",
    )
    config = Config(
        hostname="127.0.0.1",
        targets={target.id: target},
        default_target_id=target.id,
    )

    assert not config.account
    assert not config.cookie
    assert not config.mi_did
    assert config.get_enabled_targets() == [target]
    assert config.get_default_target() == target


def test_legacy_speaker_cache_migrates_without_changing_virtual_udn(tmp_path):
    payload = {
        "hostname": "127.0.0.1",
        "mi_did": "legacy-did",
        "speakers": {
            "legacy-did": {
                "did": "legacy-did",
                "device_id": "ABC-123",
                "name": "M01",
                "dlna_name": "Bedroom",
                "udn": "existing-virtual-udn",
                "local_dlna_location": "http://192.0.2.10/device.xml",
                "enabled": True,
            }
        },
    }
    (tmp_path / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    config = Config.load(str(tmp_path))
    target = config.get_default_target()

    assert target is not None
    assert target.id == "uuid:abc-123"
    assert target.kind == "dlna"
    assert target.name == "Bedroom"
    assert target.virtual_udn == "existing-virtual-udn"
    assert target.legacy_did == "legacy-did"
    assert config.mi_did == "legacy-did"


def test_target_round_trip_preserves_selection(tmp_path):
    config = Config(
        hostname="127.0.0.1",
        conf_path=str(tmp_path),
        targets={
            "uuid:renderer": OutputTargetConfig(
                id="uuid:renderer",
                name="Speaker",
                location="http://192.0.2.10/device.xml",
                udn="uuid:renderer",
            )
        },
        default_target_id="uuid:renderer",
    )
    config.save()

    loaded = Config.load(str(tmp_path))

    assert loaded.get_default_target() == config.get_default_target()


def test_target_round_trip_preserves_receiver_alias_without_using_default_target(tmp_path):
    target = OutputTargetConfig(
        id="uuid:renderer",
        name="Speaker",
        receiver_alias="Living fabric",
    )
    config = Config(
        hostname="127.0.0.1",
        conf_path=str(tmp_path),
        targets={target.id: target},
    )

    config.save()
    loaded = Config.load(str(tmp_path))

    assert loaded.get_target(target.id).receiver_alias == "Living fabric"
    assert loaded.get_target(target.id).get_receiver_alias("CastFabric") == "Living fabric"


def test_target_alias_falls_back_to_prefix_and_target_name():
    target = OutputTargetConfig(id="uuid:renderer", name="客厅音箱")

    assert target.get_receiver_alias("CastFabric") == "CastFabric · 客厅音箱"
