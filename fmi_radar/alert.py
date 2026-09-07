"""Rain warning disk and a hook for optical-flow nowcasts.

Current behaviour
-----------------
``observed_rain`` tests a circular warning cell (default 2 km radius) around
the home coordinate on the native radar grid. If any valid pixel inside the
disk is at or above the rain-rate threshold, status is ``RAIN``, else ``DRY``.

Home Assistant
--------------
``status.txt`` is a one-line MQTT payload (``RAIN`` / ``DRY``). Richer fields
live in ``radar.json`` under ``alert``. Swap the file write for an MQTT publish
later without changing this module.

Optical flow (not implemented yet)
----------------------------------
Keep successive crops as ``radar.npz`` / ``radar_prev.npz``. A future flow
module should estimate a displacement field in the crop CRS (metres) and call
``nowcast_rain(..., lead_minutes=X, displacement=flow)``. ``advect_field``
will shift ``rr`` / ``dbzh`` by that flow, then the same disk test runs on the
advected grid. ``lead_minutes=0`` always means the observed frame.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
from pyproj import Transformer
from rasterio.transform import xy

from fmi_radar.config import Config
from fmi_radar.process import RadarCrop

STATUS_RAIN = "RAIN"
STATUS_DRY = "DRY"
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
    xs, ys = xy(crop.transform, rows, cols, offset="center")
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


def advect_field(
    crop: RadarCrop,
    displacement: np.ndarray,
    lead_minutes: int,
) -> RadarCrop:
    """Shift the crop by an optical-flow displacement (placeholder).

    ``displacement`` should be an array of shape ``(2, H, W)`` in CRS metres
    (x then y), estimating motion over ``lead_minutes``. Implement with
    ``scipy.ndimage.map_coordinates`` or equivalent when the flow module lands.
    """
    raise NotImplementedError(
        "Optical-flow advection is not implemented yet. "
        "Estimate a (2, H, W) metre displacement from radar_prev.npz + "
        "radar.npz, then implement this shift."
    )


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
        raise NotImplementedError(
            f"No displacement for a {lead_minutes}-minute nowcast. "
            "Pass optical-flow output into nowcast_rain(..., displacement=...)."
        )
    advected = advect_field(crop, displacement, lead_minutes)
    alert = observed_rain(advected, config)
    alert.lead_minutes = lead_minutes
    alert.method = "optical_flow"
    return alert
