"""Rain warning disk and optical-flow nowcasts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Literal

import numpy as np
from pyproj import Transformer

from .config import Config
from .flow import advect_crop
from .process import RadarCrop

STATUS_RAIN = "RAIN"
STATUS_DRY = "DRY"
STATUS_UNAVAILABLE = "unavailable"
Method = Literal["observed", "optical_flow"]


@dataclass
class RainAlert:
    status: str
    lead_minutes: int
    method: Method
    radius_km: float
    threshold_mmh: float
    max_rr_mmh: float
    mean_rr_mmh: float
    wet_pixels: int
    pixels_in_disk: int

    def payload(self) -> str:
        """Single-line status for MQTT / status.txt."""
        return self.status

    def as_dict(self) -> dict:
        return asdict(self)


def _center_xy(crop: RadarCrop, lat: float, lon: float) -> tuple[float, float]:
    to_crs = Transformer.from_crs("EPSG:4326", crop.crs, always_xy=True)
    return to_crs.transform(lon, lat)


def disk_mask(crop: RadarCrop, lat: float, lon: float, radius_km: float) -> np.ndarray:
    """True for pixel centres within ``radius_km`` of the home coordinate."""
    x0, y0 = _center_xy(crop, lat, lon)
    rows, cols = np.indices(crop.rr.shape)
    xs, ys = crop.transform.xy(rows, cols, offset="center")
    xs = np.asarray(xs, dtype=np.float64).reshape(crop.rr.shape)
    ys = np.asarray(ys, dtype=np.float64).reshape(crop.rr.shape)
    dist_m = np.hypot(xs - x0, ys - y0)
    return dist_m <= radius_km * 1000.0


def observed_rain(crop: RadarCrop, config: Config) -> RainAlert:
    disk = disk_mask(crop, config.lat, config.lon, config.warn_radius_km)
    usable = disk & crop.valid & np.isfinite(crop.rr)
    wet = usable & (crop.rr >= config.rr_vmin)
    max_rr = float(np.nanmax(crop.rr[usable])) if np.any(usable) else 0.0
    raining = bool(np.any(wet))
    if np.any(disk):
        spatial = np.where(disk, np.nan_to_num(crop.rr, nan=0.0), np.nan)
        mean_rr = float(np.nanmean(spatial))
    else:
        mean_rr = 0.0
    return RainAlert(
        status=STATUS_RAIN if raining else STATUS_DRY,
        lead_minutes=0,
        method="observed",
        radius_km=config.warn_radius_km,
        threshold_mmh=config.rr_vmin,
        max_rr_mmh=max_rr,
        mean_rr_mmh=mean_rr,
        wet_pixels=int(np.count_nonzero(wet)),
        pixels_in_disk=int(np.count_nonzero(disk)),
    )


def will_rain_flag(alert: RainAlert | None) -> bool | None:
    if alert is None:
        return None
    return alert.status == STATUS_RAIN


def advect_field(
    crop: RadarCrop,
    displacement: np.ndarray,
    lead_minutes: int,
) -> RadarCrop:
    """Shift the crop by a Farneback flow field (pixels per 5-minute step)."""
    return advect_crop(crop, displacement, lead_minutes)


def nowcast_rain(
    crop: RadarCrop,
    config: Config,
    lead_minutes: int = 0,
    displacement: np.ndarray | None = None,
) -> RainAlert:
    """Rain disk now, or after advecting the field ``lead_minutes`` ahead."""
    if lead_minutes <= 0:
        return observed_rain(crop, config)
    if displacement is None:
        raise ValueError(
            f"No displacement for a {lead_minutes}-minute nowcast. "
            "Pass Farneback flow into nowcast_rain(..., displacement=...)."
        )
    advected = advect_field(crop, displacement, lead_minutes)
    alert = observed_rain(advected, config)
    return replace(alert, lead_minutes=lead_minutes, method="optical_flow")
