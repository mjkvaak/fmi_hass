from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from fmi_radar.flow import (
    advect_array,
    advect_crop,
    mean_step_flow,
    pair_flow,
    run_nowcast,
)
from tests.conftest import make_crop


def _uniform_flow(shape: tuple[int, int], dx: float, dy: float) -> np.ndarray:
    flow = np.zeros(shape + (2,), dtype=np.float32)
    flow[..., 0] = dx
    flow[..., 1] = dy
    return flow


def test_pair_flow_tracks_eastward_echo():
    n = 96
    shift = 12.0
    sigma = 6.0
    yy, xx = np.mgrid[0:n, 0:n]
    prev_dbz = (
        40.0 * np.exp(-((xx - 28.0) ** 2 + (yy - 48.0) ** 2) / (2.0 * sigma**2))
    ).astype(np.float32)
    nxt_dbz = (
        40.0
        * np.exp(-((xx - 28.0 - shift) ** 2 + (yy - 48.0) ** 2) / (2.0 * sigma**2))
    ).astype(np.float32)
    prev = make_crop(n=n, rr=(prev_dbz / 20.0).astype(np.float32))
    nxt = make_crop(n=n, rr=(nxt_dbz / 20.0).astype(np.float32))
    prev.dbzh = np.where(prev_dbz > 1.0, prev_dbz, np.nan)
    nxt.dbzh = np.where(nxt_dbz > 1.0, nxt_dbz, np.nan)
    flow = pair_flow(prev, nxt)
    echo = prev_dbz > 8.0
    assert float(flow[..., 0][echo].mean()) == pytest.approx(shift, abs=2.0)
    assert abs(float(flow[..., 1][echo].mean())) < 1.0
    moved = advect_array(np.nan_to_num(prev.dbzh), flow, steps=1.0)
    mass = np.nan_to_num(moved)
    weights = mass.sum()
    centroid_x = float((mass.sum(0) * np.arange(n)).sum() / weights)
    assert centroid_x == pytest.approx(28.0 + shift, abs=2.0)


def test_advect_array_shifts_pulse_east():
    field = np.zeros((9, 9), dtype=np.float32)
    field[4, 2] = 5.0
    flow = _uniform_flow((9, 9), dx=2.0, dy=0.0)
    moved = advect_array(field, flow, steps=1.0)
    assert moved[4, 4] == pytest.approx(5.0, abs=0.15)
    assert np.isnan(moved[4, 0]) or moved[4, 0] == pytest.approx(0.0, abs=0.15)


def test_advect_crop_updates_timestamp():
    crop = make_crop(n=9)
    flow = _uniform_flow((9, 9), dx=1.0, dy=0.0)
    out = advect_crop(crop, flow, lead_minutes=10)
    assert out.timestamp == crop.timestamp + timedelta(minutes=10)
    assert out.rr.shape == crop.rr.shape


def test_mean_step_flow_none_without_consecutive_five_min_frames():
    history = {0: make_crop(), -15: make_crop()}
    assert mean_step_flow(history) is None


def test_run_nowcast_requires_t0():
    with pytest.raises(ValueError, match="T=0"):
        run_nowcast({-5: make_crop()}, leads=(5,))


def test_run_nowcast_without_flow():
    crop = make_crop()
    result = run_nowcast({0: crop, -15: crop}, leads=(5, 10))
    assert result.flow_available is False
    assert result.leads == {}
    assert result.history_offsets == [-15, 0]
