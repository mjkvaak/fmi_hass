from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

from fmi_radar.config import (
    BUCKET_HOST,
    INTERVAL_MIN,
    MAX_LOOKBACK_MIN,
    MAX_NEAREST_MIN,
    Config,
)
from fmi_radar.log import get_logger

HELSINKI = ZoneInfo("Europe/Helsinki")
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class RadarObject:
    key: str
    timestamp: datetime
    url: str
    payload: bytes | None = None
    requested: datetime | None = None
    published: datetime | None = None


def _session(config: Config) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": config.user_agent})
    return session


def object_url(key: str) -> str:
    return f"{BUCKET_HOST}/{key}"


def key_for(timestamp: datetime, product: str) -> str:
    utc = timestamp.astimezone(timezone.utc)
    return f"{utc:%Y/%m/%d}/{utc:%Y%m%d%H%M}_{product}"


def parse_timestamp(value: str) -> datetime:
    """Parse ISO-8601, FMI compact UTC, or naive local Europe/Helsinki time."""
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    if len(text) == 12 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"Unrecognized timestamp {value!r}. Try 2026-09-01T15:00, "
            "2026-09-01T12:00Z, or 202609011200."
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HELSINKI)
    return parsed


def round_to_interval(moment: datetime) -> datetime:
    utc = moment.astimezone(timezone.utc).replace(second=0, microsecond=0)
    remainder = utc.minute % INTERVAL_MIN
    if remainder >= INTERVAL_MIN / 2:
        utc += timedelta(minutes=INTERVAL_MIN - remainder)
    else:
        utc -= timedelta(minutes=remainder)
    return utc


def _floor_interval(now: datetime) -> datetime:
    utc = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return utc - timedelta(minutes=utc.minute % INTERVAL_MIN)


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _head(session: requests.Session, key: str) -> requests.Response | None:
    response = session.head(object_url(key), timeout=20, allow_redirects=True)
    if response.status_code != 200:
        return None
    return response


def _ref(
    key: str,
    timestamp: datetime,
    requested: datetime | None,
    published: datetime | None = None,
) -> RadarObject:
    return RadarObject(
        key=key,
        timestamp=timestamp,
        url=object_url(key),
        payload=None,
        requested=requested,
        published=published,
    )


def expected_product_slot(now: datetime, publish_lag_min: float) -> datetime:
    """Latest 5-minute slot that should already be on S3.

    FMI writes the GeoTIFF several minutes after the product timestamp. Until
    that lag has passed, the current floor slot is usually still a 404.
    """
    slot = _floor_interval(now)
    age_min = (now.astimezone(timezone.utc) - slot).total_seconds() / 60.0
    if age_min < publish_lag_min:
        slot -= timedelta(minutes=INTERVAL_MIN)
    return slot


def find_latest_key(
    config: Config,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> tuple[str, datetime, datetime | None]:
    """Walk 5-minute slots backward until a composite object exists."""
    session = session or _session(config)
    slot = expected_product_slot(now or datetime.now(timezone.utc), config.publish_lag_min)
    steps = MAX_LOOKBACK_MIN // INTERVAL_MIN
    for _ in range(steps):
        key = key_for(slot, config.product)
        response = _head(session, key)
        if response is not None:
            LOGGER.info("Found latest composite %s", key)
            return key, slot, _parse_http_date(response.headers.get("Last-Modified"))
        LOGGER.debug("Missing composite %s", key)
        slot -= timedelta(minutes=INTERVAL_MIN)
    raise FileNotFoundError(
        f"No {config.product!r} object in the last {MAX_LOOKBACK_MIN} minutes"
    )


def find_nearest_key(
    config: Config,
    when: datetime,
    session: requests.Session | None = None,
) -> tuple[str, datetime, datetime | None]:
    """Match a requested time to the closest existing 5-minute composite."""
    session = session or _session(config)
    center = round_to_interval(when)
    max_steps = MAX_NEAREST_MIN // INTERVAL_MIN
    for step in range(max_steps + 1):
        candidates: list[datetime] = [center] if step == 0 else []
        if step:
            candidates.append(center + timedelta(minutes=step * INTERVAL_MIN))
            candidates.append(center - timedelta(minutes=step * INTERVAL_MIN))
        for slot in candidates:
            key = key_for(slot, config.product)
            response = _head(session, key)
            if response is not None:
                return key, slot, _parse_http_date(response.headers.get("Last-Modified"))
    raise FileNotFoundError(
        f"No {config.product!r} object within {MAX_NEAREST_MIN} minutes of {when.isoformat()}"
    )


def _poll_for_slot(
    config: Config,
    slot: datetime,
    session: requests.Session,
) -> tuple[str, datetime, datetime | None] | None:
    deadline = time.monotonic() + max(0.0, config.poll_seconds)
    while True:
        key = key_for(slot, config.product)
        response = _head(session, key)
        if response is not None:
            return key, slot, _parse_http_date(response.headers.get("Last-Modified"))
        newer = slot + timedelta(minutes=INTERVAL_MIN)
        key_new = key_for(newer, config.product)
        response = _head(session, key_new)
        if response is not None:
            return (
                key_new,
                newer,
                _parse_http_date(response.headers.get("Last-Modified")),
            )
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(5.0, max(0.5, deadline - time.monotonic())))


def fetch_slot(
    config: Config,
    slot: datetime,
    session: requests.Session | None = None,
) -> RadarObject | None:
    """Reference the composite at an exact 5-minute slot, or None if missing."""
    session = session or _session(config)
    utc = slot.astimezone(timezone.utc).replace(second=0, microsecond=0)
    key = key_for(utc, config.product)
    response = _head(session, key)
    if response is None:
        return None
    return _ref(
        key, utc, utc, _parse_http_date(response.headers.get("Last-Modified"))
    )


def download_object(
    config: Config, key: str, timestamp: datetime, requested: datetime | None
) -> RadarObject:
    url = object_url(key)
    response = _session(config).get(url, timeout=60)
    response.raise_for_status()
    return RadarObject(
        key=key,
        timestamp=timestamp,
        url=url,
        payload=response.content,
        requested=requested,
        published=_parse_http_date(response.headers.get("Last-Modified")),
    )


def fetch_radar(config: Config, now: datetime | None = None) -> RadarObject:
    session = _session(config)
    requested = config.when
    if requested is None:
        wall = now or datetime.now(timezone.utc)
        target = expected_product_slot(wall, config.publish_lag_min)
        polled = _poll_for_slot(config, target, session)
        if polled is not None:
            key, timestamp, published = polled
            LOGGER.info("Polled expected slot %s", key)
        else:
            LOGGER.warning("Expected S3 slot not ready within poll window; walking back")
            key, timestamp, published = find_latest_key(config, now=wall, session=session)
    else:
        key, timestamp, published = find_nearest_key(config, requested, session=session)
    return _ref(key, timestamp, requested, published)


def fetch_history(config: Config, t0: datetime) -> dict[int, RadarObject]:
    """Fetch composites at T=0 and earlier 5-minute slots (keys: -15, -10, -5, 0)."""
    session = _session(config)
    t0 = t0.astimezone(timezone.utc).replace(second=0, microsecond=0)
    frames: dict[int, RadarObject] = {}
    for offset in config.nowcast_history_min:
        rel = 0 if offset == 0 else -abs(offset)
        obj = fetch_slot(config, t0 + timedelta(minutes=rel), session=session)
        if obj is not None:
            frames[rel] = obj
        else:
            LOGGER.warning("History slot T=%s min missing", rel)
    LOGGER.debug("Fetched history frames %s", sorted(frames))
    return frames


def fetch_latest(config: Config, now: datetime | None = None) -> RadarObject:
    return fetch_radar(config, now=now)
