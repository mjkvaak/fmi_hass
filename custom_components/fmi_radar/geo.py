"""Affine geotransform helpers (no GDAL / rasterio)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class GeoTransform:
    """Maps pixel (col, row) to CRS (x, y). Same layout as GDAL/rasterio Affine."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def __iter__(self):
        yield self.a
        yield self.b
        yield self.c
        yield self.d
        yield self.e
        yield self.f
        yield 0.0
        yield 0.0
        yield 1.0

    @classmethod
    def from_origin(cls, west: float, north: float, xsize: float, ysize: float) -> GeoTransform:
        return cls(a=xsize, b=0.0, c=west, d=0.0, e=-ysize, f=north)

    @classmethod
    def from_gdal(cls, c: float, a: float, b: float, f: float, d: float, e: float) -> GeoTransform:
        return cls(a=a, b=b, c=c, d=d, e=e, f=f)

    def to_gdal(self) -> tuple[float, float, float, float, float, float]:
        return (self.c, self.a, self.b, self.f, self.d, self.e)

    def xy(self, row, col, offset: str = "center") -> tuple:
        if offset == "center":
            col = np.asarray(col, dtype=np.float64) + 0.5
            row = np.asarray(row, dtype=np.float64) + 0.5
        else:
            col = np.asarray(col, dtype=np.float64)
            row = np.asarray(row, dtype=np.float64)
        x = self.c + col * self.a + row * self.b
        y = self.f + col * self.d + row * self.e
        return x, y

    def colrow(self, x: float, y: float) -> tuple[float, float]:
        col = (x - self.c) / self.a
        row = (y - self.f) / self.e
        return col, row


def array_bounds(
    height: int, width: int, transform: GeoTransform
) -> tuple[float, float, float, float]:
    west, north = transform.c, transform.f
    east = transform.c + width * transform.a + height * transform.b
    south = transform.f + width * transform.d + height * transform.e
    return (
        min(west, east),
        min(south, north),
        max(west, east),
        max(south, north),
    )


def plotting_extent(
    height: int, width: int, transform: GeoTransform
) -> tuple[float, float, float, float]:
    """Matplotlib imshow extent (left, right, bottom, top)."""
    west, south, east, north = array_bounds(height, width, transform)
    return west, east, south, north


def sample_bilinear(field: np.ndarray, map_x: np.ndarray, map_y: np.ndarray) -> np.ndarray:
    """Sample a 2-D array at fractional column ``map_x`` and row ``map_y``."""
    height, width = field.shape
    x0 = np.floor(map_x).astype(np.int32)
    y0 = np.floor(map_y).astype(np.int32)
    x1 = x0 + 1
    y1 = y0 + 1
    wx = (map_x - x0).astype(np.float32)
    wy = (map_y - y0).astype(np.float32)
    x0c = np.clip(x0, 0, width - 1)
    x1c = np.clip(x1, 0, width - 1)
    y0c = np.clip(y0, 0, height - 1)
    y1c = np.clip(y1, 0, height - 1)
    v00 = field[y0c, x0c]
    v01 = field[y0c, x1c]
    v10 = field[y1c, x0c]
    v11 = field[y1c, x1c]
    return (
        v00 * (1.0 - wx) * (1.0 - wy)
        + v01 * wx * (1.0 - wy)
        + v10 * (1.0 - wx) * wy
        + v11 * wx * wy
    )
