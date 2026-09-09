from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from pyproj import Transformer
from rasterio.transform import from_origin

from fmi_radar.config import Config
from fmi_radar.process import RadarCrop

LAT = 60.1719  # Helsinki centre (public example)
LON = 24.9414
CRS = "EPSG:3067"
RES_M = 250.0


def home_xy(lat: float = LAT, lon: float = LON) -> tuple[float, float]:
    return Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform(lon, lat)


def make_crop(
    n: int = 21,
    res: float = RES_M,
    rr: np.ndarray | None = None,
    lat: float = LAT,
    lon: float = LON,
    timestamp: datetime | None = None,
) -> RadarCrop:
    x, y = home_xy(lat, lon)
    half = (n / 2.0) * res
    west, north = x - half, y + half
    transform = from_origin(west, north, res, res)
    if rr is None:
        field = np.zeros((n, n), dtype=np.float32)
    else:
        field = np.asarray(rr, dtype=np.float32)
        if field.shape != (n, n):
            raise ValueError(f"rr shape {field.shape} != ({n}, {n})")
    valid = np.isfinite(field)
    dbzh = np.where(valid, 20.0, np.nan).astype(np.float32)
    return RadarCrop(
        dbzh=dbzh,
        rr=field,
        valid=valid,
        bounds=(west, y - half, x + half, north),
        crs=CRS,
        timestamp=timestamp or datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc),
        nodata=255.0,
        s3_key="test.tif",
        url="https://example.invalid/test.tif",
        transform=transform,
    )


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(lat=LAT, lon=LON, outdir=tmp_path, mqtt_host=None)


@pytest.fixture
def dry_crop() -> RadarCrop:
    return make_crop()
