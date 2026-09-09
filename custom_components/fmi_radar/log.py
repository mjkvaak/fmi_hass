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

LOGGER = logging.getLogger("fmi_radar")


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
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False
