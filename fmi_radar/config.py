from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import xyzservices.providers as xyz

# Neutral public example (Helsinki railway station). Override with --lat/--lon
# or FMI_RADAR_LAT / FMI_RADAR_LON — do not commit a home coordinate.
DEFAULT_LAT = float(os.environ.get("FMI_RADAR_LAT", "60.1719"))
DEFAULT_LON = float(os.environ.get("FMI_RADAR_LON", "24.9414"))
DEFAULT_BOX_KM = 10.0

# National QC CAPPI 600 m reflectivity composite, 5-minute cadence.
DEFAULT_PRODUCT = "finland_cappi_600_dbzh_finrad_qc.tif"
BUCKET_HOST = "https://fmi-opendata-radar-geotiff.s3.eu-west-1.amazonaws.com"
INTERVAL_MIN = 5
MAX_LOOKBACK_MIN = 180
# How far to search either side of a requested historic slot.
MAX_NEAREST_MIN = 60


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Theme:
    name: str
    cmap: str
    face: str
    text: str
    muted: str
    basemap: object


def _basemap(kind: str):
    """Carto if FMI_RADAR_CARTO_API_KEY is set, otherwise OSM (no key)."""
    key = _env("FMI_RADAR_CARTO_API_KEY")
    if key:
        provider = (
            xyz.CartoDB.DarkMatter.copy()
            if kind == "dark"
            else xyz.CartoDB.Positron.copy()
        )
        provider["apikey"] = key
        return provider
    return xyz.OpenStreetMap.Mapnik


DARK = Theme(
    name="dark",
    cmap="plasma",
    face="#111318",
    text="#f2f4f8",
    muted="#9aa3b2",
    basemap=_basemap("dark"),
)
LIGHT = Theme(
    name="light",
    cmap="YlGnBu",
    face="#f4f6f8",
    text="#1b1f24",
    muted="#5c6570",
    basemap=_basemap("light"),
)

THEMES = {"dark": DARK, "light": LIGHT}


@dataclass
class Config:
    lat: float = DEFAULT_LAT
    lon: float = DEFAULT_LON
    box_km: float = DEFAULT_BOX_KM
    product: str = DEFAULT_PRODUCT
    quantity: str = "rr"  # "rr" (mm/h from Z-R) or "dbzh"
    when: datetime | None = None  # None = latest; else nearest 5-minute composite
    image_formats: tuple[str, ...] = ("png",)
    outdir: Path = field(default_factory=lambda: Path("output"))
    # Circular warning cell around lat/lon. Status is RAIN if any pixel in the disk rains.
    warn_radius_km: float = 2.0
    cmap: str | None = None
    cmap_dark: str | None = None
    cmap_light: str | None = None
    mqtt_host: str | None = field(default_factory=lambda: _env("FMI_RADAR_MQTT_HOST") or None)
    mqtt_port: int = field(
        default_factory=lambda: int(_env("FMI_RADAR_MQTT_PORT", "1883") or "1883")
    )
    mqtt_username: str | None = field(default_factory=lambda: _env("FMI_RADAR_MQTT_USER") or None)
    mqtt_password: str | None = field(
        default_factory=lambda: _env("FMI_RADAR_MQTT_PASSWORD") or None
    )
    mqtt_prefix: str = field(
        default_factory=lambda: _env("FMI_RADAR_MQTT_PREFIX") or "fmi_radar"
    )
    dpi: int = 160
    figsize: float = 6.4
    # Linear rain-rate scale (mm/h). 8 mm/h is already heavy; below vmin is transparent.
    rr_vmin: float = 0.1
    rr_vmax: float = 8.0
    rr_ticks: tuple[float, ...] = (0, 2, 4, 6, 8)
    dbz_vmin: float = 0.0
    dbz_vmax: float = 55.0
    user_agent: str = "fmi-hass-radar/0.1"
    # Wider domain for optical flow so rain can enter the 10 km map / 2 km disk.
    flow_box_km: float = 30.0
    nowcast_history_min: tuple[int, ...] = (10, 5, 0)
    nowcast_lead_min: tuple[int, ...] = (5, 10, 15)

    def cmap_for(self, theme: Theme) -> str:
        if theme.name == "dark" and self.cmap_dark:
            return self.cmap_dark
        if theme.name == "light" and self.cmap_light:
            return self.cmap_light
        return self.cmap or theme.cmap
