from __future__ import annotations

import numpy as np

from fmi_radar.config import Config
from fmi_radar.plot import _arrow_sites, _offset_label
from tests.conftest import make_crop


def test_offset_label_integer_and_fractional():
    assert _offset_label(0.0) == "T=0 min"
    assert _offset_label(5.0) == "T=+5 min"
    assert _offset_label(2.5) == "T=+2.5 min"
    assert "observed" not in _offset_label(0.0).lower()
    assert "nowcast" not in _offset_label(5.0).lower()


def test_arrow_sites_disabled_when_density_non_positive():
    crop = make_crop(n=9)
    flow = np.ones((9, 9, 2), dtype=np.float32)
    crop.rr[:] = 1.0
    assert _arrow_sites(crop, flow, Config(flow_arrow_density=0.0)) is None
    assert _arrow_sites(crop, flow, Config(flow_arrow_density=-1.0)) is None
    assert _arrow_sites(crop, flow, Config(show_flow_arrows=False)) is None


def test_arrow_sites_keep_rainy_moving_cells():
    crop = make_crop(n=16)
    crop.rr[:] = 1.0
    flow = np.zeros((16, 16, 2), dtype=np.float32)
    flow[..., 0] = 2.0
    sites = _arrow_sites(crop, flow, Config(box_km=10.0, flow_arrow_density=0.04, show_flow_arrows=True))
    assert sites is not None
    rows, cols, keep = sites
    assert keep.any()
    assert rows.size > 0 and cols.size > 0
