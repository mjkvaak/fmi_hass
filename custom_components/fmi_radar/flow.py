"""Dense optical flow nowcast from recent FMI radar crops.

Coarse-to-fine Horn–Schunck (numpy) on consecutive 5-minute frames, then
advect T=0 forward. A single-scale solve cannot track typical radar motion
(many pixels per 5 minutes) and looks like diffusion.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from time import perf_counter

import numpy as np

from .config import INTERVAL_MIN
from .geo import sample_bilinear
from .log import get_logger
from .process import RadarCrop

LOGGER = get_logger(__name__)

_PYR_MIN = 16
_MAX_LEVELS = 5
_HS_ALPHA = 15.0
_HS_ITERS = 40


def _gray(crop: RadarCrop) -> np.ndarray:
    """Reflectivity as 8-bit (empty echo → 0)."""
    dbz = np.nan_to_num(crop.dbzh, nan=0.0)
    scaled = np.clip((dbz + 10.0) * (255.0 / 65.0), 0, 255)
    return scaled.astype(np.float32)


def _smooth3(field: np.ndarray) -> np.ndarray:
    padded = np.pad(field, 1, mode="edge")
    return (
        padded[:-2, :-2]
        + 2.0 * padded[:-2, 1:-1]
        + padded[:-2, 2:]
        + 2.0 * padded[1:-1, :-2]
        + 4.0 * padded[1:-1, 1:-1]
        + 2.0 * padded[1:-1, 2:]
        + padded[2:, :-2]
        + 2.0 * padded[2:, 1:-1]
        + padded[2:, 2:]
    ) / 16.0


def _resize(field: np.ndarray, height: int, width: int) -> np.ndarray:
    src_h, src_w = field.shape
    if (src_h, src_w) == (height, width):
        return field.astype(np.float32)
    grid_y, grid_x = np.meshgrid(
        np.linspace(0.0, src_h - 1.0, height, dtype=np.float32),
        np.linspace(0.0, src_w - 1.0, width, dtype=np.float32),
        indexing="ij",
    )
    return sample_bilinear(field.astype(np.float32), grid_x, grid_y)


def _pyr_down(field: np.ndarray) -> np.ndarray:
    height, width = field.shape
    return _resize(_smooth3(field), max(height // 2, 1), max(width // 2, 1))


def _upsample_flow(
    u: np.ndarray, v: np.ndarray, shape: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray]:
    height, width = shape
    scale_x = width / u.shape[1]
    scale_y = height / u.shape[0]
    return _resize(u, height, width) * scale_x, _resize(v, height, width) * scale_y


def _warp(field: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    height, width = field.shape
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float32),
        np.arange(height, dtype=np.float32),
    )
    return sample_bilinear(field, grid_x + u, grid_y + v)


def _gradients(field: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ix = np.zeros_like(field)
    iy = np.zeros_like(field)
    ix[:, 1:-1] = (field[:, 2:] - field[:, :-2]) * 0.5
    iy[1:-1, :] = (field[2:, :] - field[:-2, :]) * 0.5
    return ix, iy


def _horn_schunck(i1: np.ndarray, i2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ix1, iy1 = _gradients(i1)
    ix2, iy2 = _gradients(i2)
    ix = 0.5 * (ix1 + ix2)
    iy = 0.5 * (iy1 + iy2)
    it = i2 - i1
    u = np.zeros_like(i1)
    v = np.zeros_like(i1)
    alpha2 = _HS_ALPHA * _HS_ALPHA
    for _ in range(_HS_ITERS):
        u_avg = _smooth3(u)
        v_avg = _smooth3(v)
        der = (ix * u_avg + iy * v_avg + it) / (alpha2 + ix * ix + iy * iy)
        u = u_avg - ix * der
        v = v_avg - iy * der
    return u, v


def pair_flow(prev: RadarCrop, nxt: RadarCrop) -> np.ndarray:
    """flow[...,0]=dx (cols), flow[...,1]=dy (rows), pixels per 5-minute step."""
    if prev.rr.shape != nxt.rr.shape:
        raise ValueError("Nowcast frames must share the same crop shape")
    t0 = perf_counter()
    i1 = _smooth3(_gray(prev))
    i2 = _smooth3(_gray(nxt))
    pyramid = [(i1, i2)]
    while len(pyramid) < _MAX_LEVELS:
        current = pyramid[-1][0]
        if min(current.shape) // 2 < _PYR_MIN:
            break
        pyramid.append((_pyr_down(pyramid[-1][0]), _pyr_down(pyramid[-1][1])))
    u = np.zeros_like(pyramid[-1][0])
    v = np.zeros_like(pyramid[-1][0])
    for level, (p1, p2) in enumerate(reversed(pyramid)):
        if level:
            u, v = _upsample_flow(u, v, p1.shape)
        warped = _warp(p2, u, v)
        du, dv = _horn_schunck(p1, warped)
        u = u + du
        v = v + dv
    flow = np.stack((u, v), axis=-1).astype(np.float32)
    LOGGER.info(
        "Optical flow %sx%s (%s pyramid level(s)) in %.2fs",
        prev.rr.shape[0],
        prev.rr.shape[1],
        len(pyramid),
        perf_counter() - t0,
    )
    return flow


def mean_step_flow(crops: dict[int, RadarCrop]) -> np.ndarray | None:
    """Average 5-minute flows from consecutive history frames."""
    ordered = sorted(k for k in crops if k <= 0)
    flows: list[np.ndarray] = []
    for older, newer in zip(ordered, ordered[1:]):
        dt = newer - older
        if dt != INTERVAL_MIN:
            continue
        flow = pair_flow(crops[older], crops[newer])
        flows.append(flow * (INTERVAL_MIN / dt))
    if not flows:
        LOGGER.debug("No consecutive 5-minute history pairs for optical flow")
        return None
    LOGGER.debug("Averaging %s optical-flow pair(s)", len(flows))
    return np.mean(np.stack(flows, axis=0), axis=0)


def advect_array(field: np.ndarray, flow: np.ndarray, steps: float) -> np.ndarray:
    height, width = field.shape
    grid_x, grid_y = np.meshgrid(np.arange(width), np.arange(height))
    map_x = (grid_x - flow[..., 0] * steps).astype(np.float32)
    map_y = (grid_y - flow[..., 1] * steps).astype(np.float32)
    filled = np.nan_to_num(field, nan=0.0).astype(np.float32)
    remapped = sample_bilinear(filled, map_x, map_y)
    inside = (map_x >= 0) & (map_x <= width - 1) & (map_y >= 0) & (map_y <= height - 1)
    return np.where(inside, remapped, np.nan).astype(np.float32)


def advect_crop(crop: RadarCrop, flow: np.ndarray, lead_minutes: float) -> RadarCrop:
    steps = lead_minutes / INTERVAL_MIN
    rr = advect_array(crop.rr, flow, steps)
    dbzh = advect_array(crop.dbzh, flow, steps)
    valid = np.isfinite(rr) & (rr > 0)
    return replace(
        crop,
        rr=rr,
        dbzh=dbzh,
        valid=valid,
        timestamp=crop.timestamp + timedelta(minutes=lead_minutes),
    )


@dataclass
class Nowcast:
    t0: datetime
    history_offsets: list[int]
    flow_available: bool
    leads: dict[int, RadarCrop]
    flow: np.ndarray | None


def run_nowcast(history: dict[int, RadarCrop], leads: tuple[int, ...]) -> Nowcast:
    if 0 not in history:
        raise ValueError("Nowcast needs a T=0 crop")
    t0 = history[0]
    flow = mean_step_flow(history)
    predicted: dict[int, RadarCrop] = {}
    if flow is not None:
        for lead in leads:
            predicted[lead] = advect_crop(t0, flow, lead)
    return Nowcast(
        t0=t0.timestamp,
        history_offsets=sorted(history),
        flow_available=flow is not None,
        leads=predicted,
        flow=flow,
    )
