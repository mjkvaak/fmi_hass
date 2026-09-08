from __future__ import annotations

from pathlib import Path

from fmi_radar.config import Config
from fmi_radar.persist import load_crop, save_crop
from tests.conftest import LAT, LON, make_crop


def test_save_and_load_roundtrip(tmp_path: Path):
    crop = make_crop()
    crop.rr[10, 10] = 3.25
    config = Config(lat=LAT, lon=LON, outdir=tmp_path)
    latest, previous = save_crop(crop, config, tmp_path)
    assert previous is None
    loaded, meta = load_crop(latest)
    assert loaded.rr[10, 10] == crop.rr[10, 10]
    assert loaded.crs == crop.crs
    assert meta["lat"] == LAT
    save_crop(crop, config, tmp_path)
    assert (tmp_path / "radar_prev.npz").exists()
