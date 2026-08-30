import json

from miair.config import Config


def _load_config(tmp_path, payload):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return Config.load(str(tmp_path))


def test_legacy_openxiaocast_default_migrates_to_castfabric(tmp_path):
    config = _load_config(
        tmp_path,
        {"hostname": "127.0.0.1", "miplay_name": "OpenXiaoCast"},
    )

    assert config.device_name_prefix == "CastFabric"
    assert config.miplay_name == "CastFabric"


def test_explicit_legacy_miplay_name_becomes_shared_device_prefix(tmp_path):
    config = _load_config(
        tmp_path,
        {"hostname": "127.0.0.1", "miplay_name": "Home Audio"},
    )

    assert config.device_name_prefix == "Home Audio"
    assert config.miplay_name == "Home Audio"


def test_new_prefix_wins_over_legacy_miplay_name(tmp_path):
    config = _load_config(
        tmp_path,
        {
            "hostname": "127.0.0.1",
            "device_name_prefix": "Living Fabric",
            "miplay_name": "Old MiPlay Name",
        },
    )

    assert config.device_name_prefix == "Living Fabric"
    assert config.miplay_name == "Living Fabric"


def test_legacy_cold_upgrade_save_is_readable_by_old_schema_and_reupgrade(tmp_path):
    legacy = {
        "account": "legacy-user",
        "password": "legacy-password",
        "mi_did": "legacy-did",
        "cookie": "userId=legacy; passToken=legacy",
        "hostname": "127.0.0.1",
        "miplay_name": "Whole Home",
        "speakers": {
            "legacy-did": {
                "did": "legacy-did",
                "device_id": "ABC-123",
                "hardware": "LX06",
                "name": "旧音箱",
                "dlna_name": "卧室",
                "udn": "stable-virtual-udn",
                "local_dlna_location": "http://192.0.2.10/device.xml",
                "enabled": True,
            }
        },
    }
    upgraded = _load_config(tmp_path, legacy)
    target = upgraded.get_default_target()
    assert target is not None
    target.receiver_alias = "卧室声场"
    upgraded.save()

    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    # v0.8's loader allowlists its constructor fields and therefore ignores
    # these v2 additions while retaining every field it still understands.
    old_schema_fields = set(legacy) | {
        "conf_path",
        "verbose",
        "proxy_enabled",
        "auto_play_on_set_uri",
        "auto_resume_on_interrupt",
        "resume_delay_seconds",
        "default_volume",
        "follow_device_volume",
        "enable_voice_control",
        "auto_restart",
        "voice_poll_interval",
        "enable_miplay",
        "miplay_port",
        "miplay_play_type",
        "miplay_http_mode",
        "miplay_content_type",
        "miplay_stream_format",
        "dlna_port",
        "web_port",
    }
    old_reader_view = {key: value for key, value in saved.items() if key in old_schema_fields}
    assert old_reader_view["mi_did"] == legacy["mi_did"]
    old_speaker = old_reader_view["speakers"]["legacy-did"]
    for key, value in legacy["speakers"]["legacy-did"].items():
        assert old_speaker[key] == value
    assert old_reader_view["miplay_name"] == "Whole Home"
    assert "targets" not in old_reader_view

    reupgraded = Config.load(str(tmp_path))
    restored = reupgraded.get_target("uuid:abc-123")
    assert restored is not None
    assert restored.virtual_udn == "stable-virtual-udn"
    assert restored.receiver_alias == "卧室声场"
