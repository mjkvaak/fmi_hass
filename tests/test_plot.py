from __future__ import annotations

import logging
from dataclasses import replace

import numpy as np

from fmi_radar.config import Config, THEMES
from fmi_radar.log import ElapsedFilter
from fmi_radar.plot import (
    _arrow_sites,
    _basemap_cache_id,
    _offset_label,
    _src_bounds,
    _tile_zoom,
    _warp_basemap_to_crop,
    crop_osm_mosaic,
    load_basemap_cache,
    save_basemap_cache,
)
from tests.conftest import LAT, LON, make_crop


def test_tile_zoom_caps_large_boxes():
    assert _tile_zoom(10.0) == 12
    assert _tile_zoom(20.0) == 11
    assert _tile_zoom(40.0) == 10


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


def test_crop_osm_mosaic_trims_padding():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[40:60, 40:60] = 255
    extent = (0.0, 100.0, 0.0, 100.0)
    cropped, new_extent = crop_osm_mosaic(img, extent, 40.0, 40.0, 60.0, 60.0)
    assert cropped.shape[0] < img.shape[0]
    assert cropped.shape[1] < img.shape[1]
    assert cropped.mean() > 200
    min_x, max_x, min_y, max_y = new_extent
    assert min_x < 40.5 and max_x > 59.5
    assert min_y < 40.5 and max_y > 59.5


def test_warp_basemap_to_crop_matches_requested_size():
    tiles = np.full((32, 32, 3), 128, dtype=np.uint8)
    crop = make_crop(n=21)
    # Synthetic mercator AABB; warp only needs a valid 3857 extent.
    extent = (24.0e6, 24.1e6, 8.3e6, 8.4e6)
    warped, out_extent = _warp_basemap_to_crop(tiles, extent, crop, out_px=16)
    assert warped.shape == (16, 16, 3)
    west, south, east, north = _src_bounds(crop)
    assert out_extent == (west, east, south, north)


def test_basemap_disk_cache_hit_until_coords_change(tmp_path):
    crop = make_crop()
    config = Config(lat=LAT, lon=LON, box_km=10.0, outdir=tmp_path)
    theme = THEMES["dark"]
    tiles = np.zeros((8, 8, 3), dtype=np.uint8)
    tiles[0, 0] = 200
    extent = (1.0, 2.0, 3.0, 4.0)
    save_basemap_cache(crop, config, theme, tiles, extent)
    loaded = load_basemap_cache(crop, config, theme)
    assert loaded is not None
    np.testing.assert_array_equal(loaded[0], tiles)
    assert loaded[1] == extent
    moved = replace(config, lon=round(LON + 0.02, 4))
    assert _basemap_cache_id(crop, moved, theme) != _basemap_cache_id(crop, config, theme)
    assert load_basemap_cache(crop, moved, theme) is None


def test_elapsed_filter_sets_seconds():
    record = logging.LogRecord("fmi_radar", logging.INFO, __file__, 1, "hi", (), None)
    filt = ElapsedFilter(t0=0.0)
    assert filt.filter(record)
    assert record.elapsed.endswith("s")
