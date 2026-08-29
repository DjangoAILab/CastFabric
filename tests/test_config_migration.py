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

