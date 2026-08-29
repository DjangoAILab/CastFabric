from miair.config import Config
from miair.identity import PRODUCT_NAME, format_device_name


def test_castfabric_is_the_default_product_and_device_prefix():
    config = Config(hostname="127.0.0.1")

    assert PRODUCT_NAME == "CastFabric"
    assert config.device_name_prefix == "CastFabric"
    assert config.miplay_name == "CastFabric"
    assert config.get_device_name("客厅音箱") == "CastFabric · 客厅音箱"


def test_device_name_formatting_avoids_empty_suffixes_and_double_prefixes():
    assert format_device_name("CastFabric", "") == "CastFabric"
    assert format_device_name("CastFabric", "CastFabric") == "CastFabric"
    assert (
        format_device_name("CastFabric", "CastFabric · 客厅")
        == "CastFabric · 客厅"
    )


def test_custom_prefix_is_trimmed_and_bounded():
    config = Config(
        hostname="127.0.0.1",
        device_name_prefix="  " + "X" * 100,
    )

    assert config.device_name_prefix == "X" * 80
    assert config.get_device_name("书房") == f"{'X' * 80} · 书房"

