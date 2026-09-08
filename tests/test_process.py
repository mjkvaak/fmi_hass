from __future__ import annotations

import numpy as np
import pytest

from fmi_radar.process import crop_stats, dbzh_to_rr, pixel_to_dbzh
from tests.conftest import make_crop


def test_pixel_to_dbzh_fmi_encoding():
    pixels = np.array([0.0, 64.0, 110.0], dtype=np.float32)
    dbzh = pixel_to_dbzh(pixels)
    np.testing.assert_allclose(dbzh, [-32.0, 0.0, 23.0])


def test_dbzh_to_rr_marshall_palmer_one_mmh():
    # Z = 200 R^1.6; at R=1 mm/h, Z=200 → ~23 dBZ.
    rr = dbzh_to_rr(np.array([23.0], dtype=np.float32))
    np.testing.assert_allclose(rr, [1.0], atol=0.01)


def test_crop_stats_empty_valid():
    crop = make_crop(rr=np.full((21, 21), np.nan, dtype=np.float32))
    crop.valid[:] = False
    assert crop_stats(crop) == {"max_dbzh": 0.0, "max_rr_mmh": 0.0, "mean_rr_mmh": 0.0}


def test_crop_stats_reports_max_and_mean():
    rr = np.zeros((21, 21), dtype=np.float32)
    rr[0, 0] = 4.0
    rr[0, 1] = 2.0
    crop = make_crop(rr=rr)
    stats = crop_stats(crop)
    assert stats["max_rr_mmh"] == pytest.approx(4.0)
    assert stats["mean_rr_mmh"] == pytest.approx(6.0 / (21 * 21))
