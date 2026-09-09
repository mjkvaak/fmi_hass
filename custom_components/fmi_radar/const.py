"""Constants for the FMI radar Home Assistant integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "fmi_radar"

CONF_BOX_KM: Final = "box_km"
CONF_WARN_RADIUS_KM: Final = "warn_radius_km"
CONF_OF_PADDING_KM: Final = "of_padding_km"
CONF_THEME: Final = "theme"
CONF_CMAP: Final = "cmap"
CONF_WRITE_GIF: Final = "write_gif"
CONF_SHOW_FLOW_ARROWS: Final = "show_flow_arrows"
CONF_FLOW_ARROW_DENSITY: Final = "flow_arrow_density"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_TIMEOUT: Final = "timeout"
CONF_ALERT_ALPHA: Final = "alert_alpha"
CONF_POLL_SECONDS: Final = "poll_seconds"

DEFAULT_NAME: Final = "Precipitation radar"
DEFAULT_BOX_KM: Final = 40.0
DEFAULT_WARN_RADIUS_KM: Final = 2.0
DEFAULT_OF_PADDING_KM: Final = 20.0
DEFAULT_THEME: Final = "hass"
THEME_HASS: Final = "hass"
DEFAULT_WRITE_GIF: Final = True
DEFAULT_FLOW_ARROW_DENSITY: Final = 0.01
DEFAULT_SCAN_INTERVAL: Final = 5
DEFAULT_TIMEOUT: Final = 240.0
DEFAULT_ALERT_ALPHA: Final = 0.05
DEFAULT_POLL_SECONDS: Final = 60.0

PLATFORMS: Final = ("sensor", "binary_sensor", "camera")
