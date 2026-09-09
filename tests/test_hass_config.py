from __future__ import annotations

from pathlib import Path

from fmi_radar.hass_config import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    config_from_entry,
    infer_ha_light_dark,
    theme_name,
)


def test_config_from_entry_maps_setup_fields(tmp_path: Path):
    cfg = config_from_entry(
        {
            CONF_LATITUDE: 60.1719,
            CONF_LONGITUDE: 24.9414,
            "box_km": 12,
            "warn_radius_km": 3,
            "of_padding_km": 15,
            "theme": "light",
            "write_gif": False,
            "show_flow_arrows": False,
            "flow_arrow_density": 0,
            "timeout": 90,
        },
        outdir=tmp_path,
    )
    assert cfg.lat == 60.1719
    assert cfg.lon == 24.9414
    assert cfg.box_km == 12
    assert cfg.warn_radius_km == 3
    assert cfg.of_padding_km == 15
    assert cfg.flow_box_km == 12 + 2 * 15
    assert cfg.write_gif is False
    assert cfg.show_flow_arrows is False
    assert cfg.flow_arrow_density == 0
    assert cfg.mqtt_host is None
    assert cfg.outdir == tmp_path


def test_options_override_data(tmp_path: Path):
    cfg = config_from_entry(
        {CONF_LATITUDE: 60.17, CONF_LONGITUDE: 24.94, "box_km": 10},
        outdir=tmp_path,
        options={"box_km": 20, "warn_radius_km": 4},
    )
    assert cfg.box_km == 20
    assert cfg.warn_radius_km == 4
    assert theme_name({CONF_LATITUDE: 1, "theme": "dark"}, {"theme": "light"}) == "light"
    assert theme_name({"theme": "hass"}, hass_theme="light") == "light"
    assert theme_name({"theme": "hass"}) == "dark"


def test_infer_ha_theme_from_name_and_colors():
    assert infer_ha_light_dark(default_theme="ios-dark-mode") == "dark"
    assert infer_ha_light_dark(default_theme="Google Light Theme") == "light"
    assert (
        infer_ha_light_dark(
            default_theme="MyTheme",
            themes={"MyTheme": {"primary-background-color": "#111318"}},
        )
        == "dark"
    )
    assert (
        infer_ha_light_dark(
            default_theme="MyTheme",
            themes={"MyTheme": {"primary-background-color": "#f4f6f8"}},
        )
        == "light"
    )
    assert infer_ha_light_dark(default_theme="default", sun_below_horizon=False) == "light"
    assert infer_ha_light_dark(default_theme="default", sun_below_horizon=True) == "dark"
