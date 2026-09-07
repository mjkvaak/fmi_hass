"""Persist radar crops as arrays for later analysis and optical flow."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine

from fmi_radar.config import Config
from fmi_radar.process import RadarCrop

LATEST_NAME = "radar.npz"
PREV_NAME = "radar_prev.npz"


def save_crop(crop: RadarCrop, config: Config, outdir: Path) -> tuple[Path, Path | None]:
    """Write ``radar.npz`` and rotate the previous file to ``radar_prev.npz``.

    Two frames on disk are enough for a future optical-flow nowcast.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    latest = outdir / LATEST_NAME
    previous: Path | None = None
    if latest.exists():
        previous = outdir / PREV_NAME
        latest.replace(previous)

    np.savez_compressed(
        latest,
        rr=crop.rr.astype(np.float32),
        dbzh=crop.dbzh.astype(np.float32),
        valid=crop.valid.astype(np.bool_),
        transform=np.array(crop.transform.to_gdal(), dtype=np.float64),
        bounds=np.array(crop.bounds, dtype=np.float64),
        timestamp_unix=np.float64(crop.timestamp.timestamp()),
        lat=np.float64(config.lat),
        lon=np.float64(config.lon),
        box_km=np.float64(config.box_km),
        warn_radius_km=np.float64(config.warn_radius_km),
        nodata=np.float64(crop.nodata),
        crs=np.array(crop.crs),
        s3_key=np.array(crop.s3_key),
        url=np.array(crop.url),
    )
    return latest, previous


def load_crop(path: Path) -> tuple[RadarCrop, dict[str, float]]:
    with np.load(path, allow_pickle=False) as data:
        transform = Affine.from_gdal(*data["transform"].tolist())
        ts = datetime.fromtimestamp(float(data["timestamp_unix"]), tz=timezone.utc)
        crop = RadarCrop(
            dbzh=data["dbzh"],
            rr=data["rr"],
            valid=data["valid"],
            bounds=tuple(float(v) for v in data["bounds"].tolist()),
            crs=str(data["crs"]),
            timestamp=ts,
            nodata=float(data["nodata"]),
            s3_key=str(data["s3_key"]),
            url=str(data["url"]),
            transform=transform,
        )
        meta = {
            "lat": float(data["lat"]),
            "lon": float(data["lon"]),
            "box_km": float(data["box_km"]),
            "warn_radius_km": float(data["warn_radius_km"]),
        }
    return crop, meta
