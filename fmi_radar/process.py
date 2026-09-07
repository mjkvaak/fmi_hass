from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.windows import Window, from_bounds

from fmi_radar.config import Config
from fmi_radar.s3 import RadarObject

# FMI GeoTIFF encoding: Z[dBZ] = 0.5 * pixel - 32
DBZ_GAIN = 0.5
DBZ_OFFSET = 32.0
# Marshall–Palmer Z-R: Z = 200 R^1.6 with Z linear (mm^6/m^3).
ZR_A = 200.0
ZR_B = 1.6


@dataclass
class RadarCrop:
    dbzh: np.ndarray
    rr: np.ndarray
    valid: np.ndarray
    bounds: tuple[float, float, float, float]  # west, south, east, north in CRS
    crs: str
    timestamp: datetime
    nodata: float
    s3_key: str
    url: str
    transform: rasterio.Affine


def pixel_to_dbzh(pixel: np.ndarray) -> np.ndarray:
    return DBZ_GAIN * pixel.astype(np.float32) - DBZ_OFFSET


def dbzh_to_rr(dbzh: np.ndarray) -> np.ndarray:
    z_linear = np.power(10.0, dbzh / 10.0)
    return np.power(z_linear / ZR_A, 1.0 / ZR_B).astype(np.float32)


def crop_radar(obj: RadarObject, config: Config) -> RadarCrop:
    half_m = config.box_km * 500.0
    with MemoryFile(obj.payload) as mem, mem.open() as src:
        transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        x, y = transformer.transform(config.lon, config.lat)
        window = from_bounds(
            x - half_m, y - half_m, x + half_m, y + half_m, transform=src.transform
        ).round_offsets().round_lengths()
        pixels = src.read(1, window=window, boundless=True)
        win_transform = src.window_transform(window)
        west, south, east, north = rasterio.windows.bounds(window, src.transform)
        nodata = src.nodata if src.nodata is not None else 255
        timestamp = obj.timestamp
        crs = src.crs.to_string() if src.crs else "EPSG:3067"

    pixels = pixels.astype(np.float32)
    valid = (pixels != nodata) & (pixels > 0)
    dbzh = pixel_to_dbzh(pixels)
    rr = np.zeros_like(dbzh)
    rr[valid] = dbzh_to_rr(dbzh[valid])
    dbzh = np.where(valid, dbzh, np.nan)
    rr = np.where(valid, rr, np.nan)

    return RadarCrop(
        dbzh=dbzh,
        rr=rr,
        valid=valid,
        bounds=(west, south, east, north),
        crs=crs,
        timestamp=timestamp,
        nodata=float(nodata),
        s3_key=obj.key,
        url=obj.url,
        transform=win_transform,
    )


def extract_box(crop: RadarCrop, lat: float, lon: float, box_km: float) -> RadarCrop:
    """Cut a smaller square around lat/lon from an already cropped mosaic."""
    half_m = box_km * 500.0
    transformer = Transformer.from_crs("EPSG:4326", crop.crs, always_xy=True)
    x, y = transformer.transform(lon, lat)
    window = from_bounds(
        x - half_m, y - half_m, x + half_m, y + half_m, transform=crop.transform
    ).round_offsets().round_lengths()
    row = max(int(window.row_off), 0)
    col = max(int(window.col_off), 0)
    height = int(window.height)
    width = int(window.width)
    row_end = min(row + height, crop.rr.shape[0])
    col_end = min(col + width, crop.rr.shape[1])
    sl = (slice(row, row_end), slice(col, col_end))
    win = Window(col, row, col_end - col, row_end - row)
    new_transform = rasterio.windows.transform(win, crop.transform)
    west, south, east, north = rasterio.windows.bounds(win, crop.transform)
    return RadarCrop(
        dbzh=crop.dbzh[sl].copy(),
        rr=crop.rr[sl].copy(),
        valid=crop.valid[sl].copy(),
        bounds=(west, south, east, north),
        crs=crop.crs,
        timestamp=crop.timestamp,
        nodata=crop.nodata,
        s3_key=crop.s3_key,
        url=crop.url,
        transform=new_transform,
    )


def crop_stats(crop: RadarCrop) -> dict[str, float]:
    if not np.any(crop.valid):
        return {"max_dbzh": 0.0, "max_rr_mmh": 0.0, "mean_rr_mmh": 0.0}
    return {
        "max_dbzh": float(np.nanmax(crop.dbzh)),
        "max_rr_mmh": float(np.nanmax(crop.rr)),
        "mean_rr_mmh": float(np.nanmean(crop.rr)),
    }
