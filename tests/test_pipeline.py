from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fmi_radar.config import Config
from fmi_radar.pipeline import _align_lead_min, _gif_offsets, _write_stable_images


def test_gif_offsets_includes_start_and_horizon():
    config = Config(gif_step_min=2.5)
    offsets = _gif_offsets(config, 15.0)
    assert offsets[0] == 0.0
    assert offsets[-1] == 15.0
    assert 2.5 in offsets
    assert 7.5 in offsets


def test_gif_offsets_zero_horizon():
    assert _gif_offsets(Config(), 0.0) == [0.0]


def test_align_lead_min_historic_stays_at_product():
    config = Config(when=datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc), gif_step_min=2.5)
    product = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
    assert _align_lead_min(product, config) == 0.0


def test_align_lead_min_live_rounds_lag_to_gif_step():
    product = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 4, 12, 8, tzinfo=timezone.utc)
    config = Config(when=None, gif_step_min=2.5, max_advect_min=30.0)
    with patch("fmi_radar.pipeline.datetime") as dt:
        dt.now.return_value = now
        aligned = _align_lead_min(product, config)
    assert aligned == 7.5


def test_write_stable_images_copies_first_of_each_format(tmp_path: Path):
    dark = tmp_path / "radar_dark.png"
    light = tmp_path / "radar_light.png"
    svg = tmp_path / "radar_dark.svg"
    dark.write_bytes(b"dark")
    light.write_bytes(b"light")
    svg.write_text("<svg/>")
    stable = _write_stable_images(
        {"dark_png": dark, "light_png": light, "dark_svg": svg},
        tmp_path,
    )
    assert Path(stable["png"]).read_bytes() == b"dark"
    assert Path(stable["svg"]).read_text() == "<svg/>"
