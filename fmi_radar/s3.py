from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from fmi_radar.config import (
    BUCKET_HOST,
    INTERVAL_MIN,
    MAX_LOOKBACK_MIN,
    MAX_NEAREST_MIN,
    Config,
)

HELSINKI = ZoneInfo("Europe/Helsinki")


@dataclass(frozen=True)
class RadarObject:
    key: str
    timestamp: datetime
    payload: bytes
    url: str
    requested: datetime | None = None


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


def _head_ok(session: requests.Session, key: str) -> bool:
    response = session.head(object_url(key), timeout=20, allow_redirects=True)
    return response.status_code == 200


def find_latest_key(
    config: Config,
    now: datetime | None = None,
    session: requests.Session | None = None,
) -> tuple[str, datetime]:
    """Walk 5-minute slots backward until a composite object exists."""
    session = session or _session(config)
    slot = _floor_interval(now or datetime.now(timezone.utc))
    steps = MAX_LOOKBACK_MIN // INTERVAL_MIN
    for _ in range(steps):
        key = key_for(slot, config.product)
        if _head_ok(session, key):
            return key, slot
        slot -= timedelta(minutes=INTERVAL_MIN)
    raise FileNotFoundError(
        f"No {config.product!r} object in the last {MAX_LOOKBACK_MIN} minutes"
    )


def find_nearest_key(
    config: Config,
    when: datetime,
    session: requests.Session | None = None,
) -> tuple[str, datetime]:
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
            if _head_ok(session, key):
                return key, slot
    raise FileNotFoundError(
        f"No {config.product!r} object within {MAX_NEAREST_MIN} minutes of {when.isoformat()}"
    )


def fetch_slot(
    config: Config,
    slot: datetime,
    session: requests.Session | None = None,
) -> RadarObject | None:
    """GET the composite at an exact 5-minute slot, or None if missing."""
    session = session or _session(config)
    utc = slot.astimezone(timezone.utc).replace(second=0, microsecond=0)
    key = key_for(utc, config.product)
    if not _head_ok(session, key):
        return None
    url = object_url(key)
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return RadarObject(key=key, timestamp=utc, payload=response.content, url=url, requested=utc)


def download_object(config: Config, key: str, timestamp: datetime, requested: datetime | None) -> RadarObject:
    url = object_url(key)
    response = _session(config).get(url, timeout=60)
    response.raise_for_status()
    return RadarObject(
        key=key, timestamp=timestamp, payload=response.content, url=url, requested=requested
    )


def fetch_radar(config: Config, now: datetime | None = None) -> RadarObject:
    session = _session(config)
    requested = config.when
    if requested is None:
        key, timestamp = find_latest_key(config, now=now, session=session)
    else:
        key, timestamp = find_nearest_key(config, requested, session=session)
    return download_object(config, key, timestamp, requested)


def fetch_history(config: Config, t0: datetime) -> dict[int, RadarObject]:
    """Fetch composites at T=0 and earlier 5-minute slots (keys: -10, -5, 0)."""
    session = _session(config)
    t0 = t0.astimezone(timezone.utc).replace(second=0, microsecond=0)
    frames: dict[int, RadarObject] = {}
    for offset in config.nowcast_history_min:
        rel = 0 if offset == 0 else -abs(offset)
        obj = fetch_slot(config, t0 + timedelta(minutes=rel), session=session)
        if obj is not None:
            frames[rel] = obj
    return frames


def fetch_latest(config: Config, now: datetime | None = None) -> RadarObject:
    return fetch_radar(config, now=now)
