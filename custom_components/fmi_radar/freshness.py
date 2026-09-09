"""Reject live FMI composites that are too old to nowcast T=0…+15."""

from __future__ import annotations

from datetime import datetime, timezone

from .config import Config
from .log import get_logger

LOGGER = get_logger(__name__)


class StaleRadarError(RuntimeError):
    """Latest FMI composite is too old for a wall-clock T=0…+15 nowcast."""


def product_age_minutes(product_time: datetime, now: datetime | None = None) -> float:
    wall = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return (wall - product_time.astimezone(timezone.utc)).total_seconds() / 60.0


def ensure_live_product_fresh(
    product_time: datetime,
    config: Config,
    now: datetime | None = None,
) -> float:
    """Return product age in minutes, or raise ``StaleRadarError`` on live runs.

    Historic ``config.when`` skips the check. Live runs need the composite
    within ``max_product_age_min`` (default 15) so advection can cover
    wall-clock T=0 through T=+15.
    """
    age = product_age_minutes(product_time, now)
    limit = float(config.max_product_age_min)
    LOGGER.info(
        "FMI product time %s is %.1f min old (freshness limit %.0f min)",
        product_time.astimezone(timezone.utc).isoformat(),
        age,
        limit,
    )
    if config.when is not None:
        LOGGER.debug("Historic --time run; not enforcing live freshness")
        return age
    if age > limit + 1e-6:
        raise StaleRadarError(
            f"FMI radar product is {age:.1f} min old "
            f"(limit {limit:.0f} min). A wall-clock T=0…+15 nowcast is not possible."
        )
    return age
