from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from fmi_radar.config import Config, DEFAULT_PRODUCT
from fmi_radar.s3 import (
    RadarObject,
    expected_product_slot,
    fetch_history,
    fetch_slot,
    find_latest_key,
    key_for,
    object_url,
    parse_timestamp,
    round_to_interval,
)


def test_parse_compact_utc():
    parsed = parse_timestamp("202609040300")
    assert parsed == datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)


def test_parse_iso_zulu():
    parsed = parse_timestamp("2026-09-01T12:00Z")
    assert parsed == datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_parse_naive_helsinki():
    parsed = parse_timestamp("2026-09-01T15:00")
    assert parsed.tzinfo == ZoneInfo("Europe/Helsinki")
    assert parsed.hour == 15


def test_parse_rejects_garbage():
    with pytest.raises(ValueError, match="Unrecognized timestamp"):
        parse_timestamp("not-a-time")


def test_round_to_interval():
    assert round_to_interval(datetime(2026, 9, 4, 12, 7, tzinfo=timezone.utc)) == datetime(
        2026, 9, 4, 12, 5, tzinfo=timezone.utc
    )
    assert round_to_interval(datetime(2026, 9, 4, 12, 8, tzinfo=timezone.utc)) == datetime(
        2026, 9, 4, 12, 10, tzinfo=timezone.utc
    )


def test_expected_product_slot_waits_for_publish_lag():
    now = datetime(2026, 9, 4, 12, 7, tzinfo=timezone.utc)
    assert expected_product_slot(now, publish_lag_min=5.0) == datetime(
        2026, 9, 4, 12, 0, tzinfo=timezone.utc
    )
    later = datetime(2026, 9, 4, 12, 16, tzinfo=timezone.utc)
    assert expected_product_slot(later, publish_lag_min=5.0) == datetime(
        2026, 9, 4, 12, 10, tzinfo=timezone.utc
    )


def test_key_for_and_object_url():
    stamp = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
    key = key_for(stamp, DEFAULT_PRODUCT)
    assert key == f"2026/09/04/202609040300_{DEFAULT_PRODUCT}"
    assert object_url(key).endswith(key)


def test_find_latest_key_walks_back_until_head_succeeds():
    config = Config()
    session = MagicMock()
    missing = MagicMock(status_code=404)
    found = MagicMock(status_code=200, headers={"Last-Modified": "Fri, 04 Sep 2026 03:04:00 GMT"})
    session.head.side_effect = [missing, found]

    key, slot, published = find_latest_key(
        config,
        now=datetime(2026, 9, 4, 3, 12, tzinfo=timezone.utc),
        session=session,
    )
    assert slot == datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
    assert key.endswith(f"202609040300_{config.product}")
    assert published is not None
    assert published.tzinfo is not None


def test_fetch_slot_returns_none_on_miss():
    session = MagicMock()
    session.head.return_value = MagicMock(status_code=404)
    assert fetch_slot(Config(), datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc), session) is None


def test_fetch_history_skips_missing_slots():
    t0 = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)
    config = Config(nowcast_history_min=(10, 5, 0))

    def fake_fetch(_config, slot, session=None):
        offset = int((slot - t0).total_seconds() / 60)
        if offset == -5:
            return None
        return RadarObject(key=f"{offset}.tif", timestamp=slot, url="https://example.invalid")

    with patch("fmi_radar.s3._session"), patch("fmi_radar.s3.fetch_slot", side_effect=fake_fetch):
        frames = fetch_history(config, t0)
    assert set(frames) == {-10, 0}
