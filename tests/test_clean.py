from __future__ import annotations

import numpy as np

from fmi_radar.clean import MIN_ECHO_PIXELS, despike_crop
from tests.conftest import make_crop


def test_despike_drops_one_and_two_pixel_islands():
    n = 21
    rr = np.zeros((n, n), dtype=np.float32)
    rr[2, 2] = 1.0
    rr[8, 8] = 1.0
    rr[8, 9] = 1.0
    crop = make_crop(n=n, rr=rr)
    crop.dbzh = np.where(rr > 0, 20.0, np.nan).astype(np.float32)
    crop.valid = np.isfinite(crop.dbzh)
    cleaned = despike_crop(crop, rr_min=0.1)
    assert not np.any(np.nan_to_num(cleaned.rr) > 0)


def test_despike_keeps_three_pixel_and_larger_patches():
    n = 21
    rr = np.zeros((n, n), dtype=np.float32)
    rr[10, 9:12] = 1.2
    rr[4:8, 4:8] = 2.0
    crop = make_crop(n=n, rr=rr)
    crop.dbzh = np.where(rr > 0, 25.0, np.nan).astype(np.float32)
    crop.valid = np.isfinite(crop.dbzh)
    cleaned = despike_crop(crop, rr_min=0.1)
    np.testing.assert_allclose(cleaned.rr[10, 9:12], [1.2, 1.2, 1.2])
    np.testing.assert_allclose(cleaned.rr[4:8, 4:8], np.full((4, 4), 2.0))


def test_despike_does_not_eat_connected_rain_when_min_is_three():
    assert MIN_ECHO_PIXELS == 3
    n = 15
    rr = np.zeros((n, n), dtype=np.float32)
    rr[7, 5:10] = 0.8
    crop = make_crop(n=n, rr=rr)
    crop.dbzh = np.where(rr > 0, 18.0, np.nan).astype(np.float32)
    crop.valid = np.isfinite(crop.dbzh)
    cleaned = despike_crop(crop, rr_min=0.1)
    assert int(np.count_nonzero(np.nan_to_num(cleaned.rr) >= 0.1)) == 5
