"""Wall-clock timeout for download + render (Linux SIGALRM)."""

from __future__ import annotations

import signal
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RenderTimeout(TimeoutError):
    """Download/render exceeded the configured time budget."""


def call_with_timeout(seconds: float, fn: Callable[..., T], *args, **kwargs) -> T:
    if seconds <= 0:
        return fn(*args, **kwargs)

    def _handler(_signum, _frame):
        raise RenderTimeout(f"Timed out after {seconds:.0f}s")

    previous = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)
