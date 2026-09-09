"""Dense optical flow nowcast from recent FMI radar crops.

Horn–Schunck (numpy) on T=-10 → T=-5 and T=-5 → T=0, then advect T=0
forward. Avoids OpenCV, which has no musllinux wheels for Home Assistant
Container (Alpine).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from time import perf_counter

import numpy as np

from .config import INTERVAL_MIN, Config
from .geo import sample_bilinear
from .log import get_logger
from .process import RadarCrop

LOGGER = get_logger(__name__)


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


def pair_flow(prev: RadarCrop, nxt: RadarCrop) -> np.ndarray:
    """flow[...,0]=dx (cols), flow[...,1]=dy (rows), pixels per 5-minute step."""
    if prev.rr.shape != nxt.rr.shape:
        raise ValueError("Nowcast frames must share the same crop shape")
    t0 = perf_counter()
    i1 = _gray(prev)
    i2 = _gray(nxt)
    ix = np.zeros_like(i1)
    iy = np.zeros_like(i1)
    ix[:, 1:-1] = (i1[:, 2:] - i1[:, :-2]) * 0.5
    iy[1:-1, :] = (i1[2:, :] - i1[:-2, :]) * 0.5
    it = i2 - i1
    u = np.zeros_like(i1)
    v = np.zeros_like(i1)
    alpha2 = 1.0
    for _ in range(20):
        u_avg = _smooth3(u)
        v_avg = _smooth3(v)
        der = (ix * u_avg + iy * v_avg + it) / (alpha2 + ix * ix + iy * iy)
        u = u_avg - ix * der
        v = v_avg - iy * der
    flow = np.stack((u, v), axis=-1).astype(np.float32)
    LOGGER.info(
        "Optical flow %sx%s in %.2fs",
        prev.rr.shape[0],
        prev.rr.shape[1],
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
