"""Shared loggers.

Home Assistant uses the same Python logging module. Set

    logger:
      logs:
        fmi_radar: debug

in ``configuration.yaml`` to see library + integration messages. The CLI
configures a stream handler in ``configure_cli_logging``.
"""

from __future__ import annotations

import logging
import sys
from time import perf_counter

LOGGER = logging.getLogger("fmi_radar")


class ElapsedFilter(logging.Filter):
    """Add ``elapsed`` (seconds since CLI logging was configured)."""

    def __init__(self, t0: float | None = None) -> None:
        super().__init__()
        self.t0 = t0 if t0 is not None else perf_counter()

    def filter(self, record: logging.LogRecord) -> bool:
        record.elapsed = f"{perf_counter() - self.t0:5.1f}s"
        return True


def get_logger(name: str | None = None) -> logging.Logger:
    if not name:
        return LOGGER
    if name == "fmi_radar" or name.startswith("fmi_radar."):
        return logging.getLogger(name)
    return logging.getLogger(f"fmi_radar.{name}")


def configure_cli_logging(level: int = logging.INFO) -> None:
    """Emit ``fmi_radar`` logs to stderr when not running under Home Assistant."""
    if LOGGER.handlers:
        LOGGER.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(ElapsedFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d %(elapsed)s %(levelname)s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False
