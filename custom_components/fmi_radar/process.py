from __future__ import annotations

import io
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

import numpy as np
from PIL import Image
from pyproj import Transformer

from .config import Config
from .geo import GeoTransform, array_bounds
from .log import get_logger
from .s3 import RadarObject, download_object

LOGGER = get_logger(__name__)

Image.MAX_IMAGE_PIXELS = None

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
    transform: GeoTransform


def pixel_to_dbzh(pixel: np.ndarray) -> np.ndarray:
    return DBZ_GAIN * pixel.astype(np.float32) - DBZ_OFFSET


def dbzh_to_rr(dbzh: np.ndarray) -> np.ndarray:
    z_linear = np.power(10.0, dbzh / 10.0)
    return np.power(z_linear / ZR_A, 1.0 / ZR_B).astype(np.float32)


def _arrays_from_pixels(pixels: np.ndarray, nodata: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pixels = pixels.astype(np.float32)
    valid = (pixels != nodata) & (pixels > 0)
    dbzh = pixel_to_dbzh(pixels)
    rr = np.zeros_like(dbzh)
    rr[valid] = dbzh_to_rr(dbzh[valid])
    dbzh = np.where(valid, dbzh, np.nan)
    rr = np.where(valid, rr, np.nan)
    return dbzh, rr, valid


def _transform_from_tiff(image: Image.Image) -> tuple[GeoTransform, str, float]:
    tags = image.tag_v2
    scale = tags.get(33550)
    tie = tags.get(33922)
    if scale is None or tie is None:
        raise ValueError("GeoTIFF is missing ModelPixelScale or ModelTiepoint")
    scale_x, scale_y = float(scale[0]), float(scale[1])
    pix_i, pix_j = float(tie[0]), float(tie[1])
    x, y = float(tie[3]), float(tie[4])
    a = scale_x
    e = -scale_y
    transform = GeoTransform(
        a=a,
        b=0.0,
        c=x - pix_i * a,
        d=0.0,
        e=e,
        f=y - pix_j * e,
    )
    nodata = float(tags.get(42113, 255) or 255)
    return transform, "EPSG:3067", nodata


def _window_slices(
    transform: GeoTransform,
    shape: tuple[int, int],
    lat: float,
    lon: float,
    box_km: float,
    crs: str,
):
    half_m = box_km * 500.0
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    col0, row0 = transform.colrow(x - half_m, y + half_m)
    col1, row1 = transform.colrow(x + half_m, y - half_m)
    col_a, col_b = sorted((col0, col1))
    row_a, row_b = sorted((row0, row1))
    height, width = shape
    col = max(int(round(col_a)), 0)
    row = max(int(round(row_a)), 0)
    col_end = min(int(round(col_b)), width)
    row_end = min(int(round(row_b)), height)
    if col_end <= col or row_end <= row:
        raise ValueError("Crop window is empty")
    sl = (slice(row, row_end), slice(col, col_end))
    new_transform = GeoTransform(
        a=transform.a,
        b=transform.b,
        c=transform.c + col * transform.a + row * transform.b,
        d=transform.d,
        e=transform.e,
        f=transform.f + col * transform.d + row * transform.e,
    )
    bounds = array_bounds(row_end - row, col_end - col, new_transform)
    return sl, new_transform, bounds


def _crop_from_tiff_bytes(obj: RadarObject, config: Config, payload: bytes) -> RadarCrop:
    with Image.open(io.BytesIO(payload)) as image:
        full = np.array(image)
        transform, crs, nodata = _transform_from_tiff(image)
    if full.ndim == 3:
        full = full[..., 0]
    sl, win_transform, bounds = _window_slices(
        transform, full.shape, config.lat, config.lon, config.box_km, crs
    )
    dbzh, rr, valid = _arrays_from_pixels(full[sl], nodata)
    return RadarCrop(
        dbzh=dbzh,
        rr=rr,
        valid=valid,
        bounds=bounds,
        crs=crs,
        timestamp=obj.timestamp,
        nodata=nodata,
        s3_key=obj.key,
        url=obj.url,
        transform=win_transform,
    )


def _crop_via_rasterio(obj: RadarObject, config: Config) -> RadarCrop:
    """Optional windowed HTTP Range read when GDAL/rasterio is installed (CLI)."""
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.windows import from_bounds

    @contextmanager
    def _open():
        if obj.payload:
            with MemoryFile(obj.payload) as mem, mem.open() as src:
                yield src
            return
        env = rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
            GDAL_HTTP_USERAGENT=config.user_agent,
            AWS_NO_SIGN_REQUEST="YES",
            CPL_VSIL_CURL_USE_HEAD="YES",
        )
        with env, rasterio.open(f"/vsicurl/{obj.url}") as src:
            yield src

    with _open() as src:
        half_m = config.box_km * 500.0
        transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        x, y = transformer.transform(config.lon, config.lat)
        window = (
            from_bounds(
                x - half_m, y - half_m, x + half_m, y + half_m, transform=src.transform
            )
            .round_offsets()
            .round_lengths()
        )
        pixels = src.read(1, window=window, boundless=True)
        gdal = src.window_transform(window).to_gdal()
        win_transform = GeoTransform.from_gdal(*gdal)
        west, south, east, north = rasterio.windows.bounds(window, src.transform)
        nodata = src.nodata if src.nodata is not None else 255
        crs = src.crs.to_string() if src.crs else "EPSG:3067"
    dbzh, rr, valid = _arrays_from_pixels(pixels, float(nodata))
    return RadarCrop(
        dbzh=dbzh,
        rr=rr,
        valid=valid,
        bounds=(west, south, east, north),
        crs=crs,
        timestamp=obj.timestamp,
        nodata=float(nodata),
        s3_key=obj.key,
        url=obj.url,
        transform=win_transform,
    )


def crop_radar(obj: RadarObject, config: Config) -> RadarCrop:
    """Crop a local window. Prefer GDAL Range reads when rasterio is installed."""
    t0 = perf_counter()
    crop = None
    if not obj.payload:
        try:
            crop = _crop_via_rasterio(obj, config)
        except Exception as exc:
            LOGGER.info("Windowed rasterio read skipped (%s)", type(exc).__name__)
    if crop is None:
        payload = obj.payload
        source = obj
        if not payload:
            source = download_object(config, obj.key, obj.timestamp, obj.requested)
            payload = source.payload or b""
        crop = _crop_from_tiff_bytes(source, config, payload)
    LOGGER.info(
        "Radar window %s box=%.1f km shape=%sx%s in %.1fs",
        obj.key,
        config.box_km,
        crop.rr.shape[0],
        crop.rr.shape[1],
        perf_counter() - t0,
    )
    return crop


def _box_slices(crop: RadarCrop, lat: float, lon: float, box_km: float):
    return _window_slices(crop.transform, crop.rr.shape, lat, lon, box_km, crop.crs)


def extract_box(crop: RadarCrop, lat: float, lon: float, box_km: float) -> RadarCrop:
    """Cut a smaller square around lat/lon from an already cropped mosaic."""
    sl, new_transform, bounds = _box_slices(crop, lat, lon, box_km)
    return RadarCrop(
        dbzh=crop.dbzh[sl].copy(),
        rr=crop.rr[sl].copy(),
        valid=crop.valid[sl].copy(),
        bounds=bounds,
        crs=crop.crs,
        timestamp=crop.timestamp,
        nodata=crop.nodata,
        s3_key=crop.s3_key,
        url=crop.url,
        transform=new_transform,
    )


def extract_flow(flow: np.ndarray, crop: RadarCrop, lat: float, lon: float, box_km: float) -> np.ndarray:
    sl, _, _ = _box_slices(crop, lat, lon, box_km)
    return flow[sl].copy()


def crop_stats(crop: RadarCrop) -> dict[str, float]:
    if not np.any(crop.valid):
        return {"max_dbzh": 0.0, "max_rr_mmh": 0.0, "mean_rr_mmh": 0.0}
    return {
        "max_dbzh": float(np.nanmax(crop.dbzh)),
        "max_rr_mmh": float(np.nanmax(crop.rr)),
        "mean_rr_mmh": float(np.nanmean(crop.rr)),
    }
