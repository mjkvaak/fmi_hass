from __future__ import annotations

import numpy as np
import pytest

from fmi_radar.alert import (
    STATUS_DRY,
    STATUS_RAIN,
    nowcast_rain,
    observed_rain,
    will_rain_flag,
)
from fmi_radar.config import Config
from tests.conftest import LAT, LON, make_crop


def test_observed_rain_dry(config: Config):
    alert = observed_rain(make_crop(), config)
    assert alert.status == STATUS_DRY
    assert alert.lead_minutes == 0
    assert alert.method == "observed"
    assert alert.wet_pixels == 0
    assert alert.pixels_in_disk > 0
    assert alert.mean_rr_mmh == pytest.approx(0.0)


def test_observed_rain_when_center_exceeds_threshold(config: Config):
    rr = np.zeros((21, 21), dtype=np.float32)
    rr[10, 10] = 1.5
    alert = observed_rain(make_crop(rr=rr), config)
    assert alert.status == STATUS_RAIN
    assert alert.wet_pixels >= 1
    assert alert.max_rr_mmh == pytest.approx(1.5)
    assert alert.payload() == STATUS_RAIN


def test_will_rain_flag():
    assert will_rain_flag(None) is None
    dry = observed_rain(make_crop(), Config(lat=LAT, lon=LON))
    assert will_rain_flag(dry) is False
    rr = np.zeros((21, 21), dtype=np.float32)
    rr[10, 10] = 2.0
    wet = observed_rain(make_crop(rr=rr), Config(lat=LAT, lon=LON))
    assert will_rain_flag(wet) is True


def test_nowcast_rain_requires_displacement_for_leads(config: Config):
    with pytest.raises(ValueError, match="No displacement"):
        nowcast_rain(make_crop(), config, lead_minutes=5)


def test_nowcast_rain_zero_lead_is_observed(config: Config):
    alert = nowcast_rain(make_crop(), config, lead_minutes=0)
    assert alert.method == "observed"
    assert alert.lead_minutes == 0
