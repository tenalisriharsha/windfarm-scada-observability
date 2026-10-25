"""Pure staleness-detection helpers, kept separate from I/O for easy testing."""

from __future__ import annotations

import math


def seen_age(last_success_monotonic: float | None, now_monotonic: float) -> float:
    """Seconds since the last successful poll, or +inf if never successfully polled."""
    if last_success_monotonic is None:
        return math.inf
    return max(0.0, now_monotonic - last_success_monotonic)


def is_stale(last_success_monotonic: float | None, now_monotonic: float, threshold_s: float) -> bool:
    """True if the turbine hasn't been successfully polled within ``threshold_s``."""
    return seen_age(last_success_monotonic, now_monotonic) > threshold_s
