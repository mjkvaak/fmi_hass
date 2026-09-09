from __future__ import annotations

from pathlib import Path

from fmi_radar.config import DEFAULT_LAT, DEFAULT_LON
from fmi_radar.hass_config import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    config_from_entry,
    coordinates_in_radar_coverage,
    infer_ha_light_dark,
    theme_name,
    default_setup_lat_lon,
)


def test_config_from_entry_maps_setup_fields(tmp_path: Path):
    cfg = config_from_entry(
        {
            CONF_LATITUDE: DEFAULT_LAT,
            CONF_LONGITUDE: DEFAULT_LON,
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
    assert cfg.lat == DEFAULT_LAT
    assert cfg.lon == DEFAULT_LON
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
        {CONF_LATITUDE: DEFAULT_LAT, CONF_LONGITUDE: DEFAULT_LON, "box_km": 10},
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


def test_default_setup_lat_lon_prefers_hass_home_then_helsinki():
    assert default_setup_lat_lon(61.5, 23.8) == (61.5, 23.8)
    assert default_setup_lat_lon(0.0, 0.0) == (DEFAULT_LAT, DEFAULT_LON)
    assert default_setup_lat_lon(None, None) == (DEFAULT_LAT, DEFAULT_LON)
    assert default_setup_lat_lon(52.37, 4.89) == (DEFAULT_LAT, DEFAULT_LON)


def test_coordinates_in_radar_coverage():
    assert coordinates_in_radar_coverage(60.1719, 24.9414)
    assert coordinates_in_radar_coverage(59.437, 24.754)
    assert coordinates_in_radar_coverage(59.329, 18.069)
    assert coordinates_in_radar_coverage(69.649, 18.955)
    assert not coordinates_in_radar_coverage(59.914, 10.752)
    assert not coordinates_in_radar_coverage(57.709, 11.975)
    assert not coordinates_in_radar_coverage(52.37, 4.89)
