from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fmi_radar.config import Config
from fmi_radar.freshness import StaleRadarError, ensure_live_product_fresh, product_age_minutes


def test_product_age_minutes():
    product = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 9, 6, 12, tzinfo=timezone.utc)
    assert product_age_minutes(product, now) == pytest.approx(12.0)


def test_live_product_within_15_min_ok():
    product = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
    now = product + timedelta(minutes=15)
    age = ensure_live_product_fresh(product, Config(when=None), now=now)
    assert age == pytest.approx(15.0)


def test_live_product_older_than_15_min_raises():
    product = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
    now = product + timedelta(minutes=15, seconds=1)
    with pytest.raises(StaleRadarError, match="15"):
        ensure_live_product_fresh(product, Config(when=None), now=now)


def test_historic_time_skips_freshness():
    product = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
    now = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
    age = ensure_live_product_fresh(product, Config(when=product), now=now)
    assert age > 15
