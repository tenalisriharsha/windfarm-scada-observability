"""Unit tests for the pure helper logic in scripts/perf_test.py.

The script itself orchestrates real subprocesses and a real Docker
container (exercised manually, not in this fast unit suite -- see
docs/performance.md for how it's actually run). This only covers the
percentile math, which is easy to get subtly wrong.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "perf_test.py"
_spec = importlib.util.spec_from_file_location("perf_test", _SCRIPT_PATH)
perf_test = importlib.util.module_from_spec(_spec)
sys.modules["perf_test"] = perf_test
_spec.loader.exec_module(perf_test)

percentile = perf_test.percentile


def test_percentile_empty_list_returns_zero():
    assert percentile([], 50) == 0.0


def test_percentile_single_value():
    assert percentile([5.0], 99) == 5.0


def test_percentile_p50_of_odd_count_is_the_middle_value():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0


def test_percentile_p0_is_min_and_p100_is_max():
    values = [10.0, 1.0, 7.0, 3.0]
    sorted_values = sorted(values)
    assert percentile(sorted_values, 0) == 1.0
    assert percentile(sorted_values, 100) == 10.0


def test_percentile_interpolates_between_adjacent_values():
    # Four sorted values: indices 0..3. p50 -> k=1.5 -> interpolate 2.0..3.0 at .5
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)


def test_percentile_is_monotonic_non_decreasing():
    values = sorted([3.0, 1.0, 9.0, 4.0, 2.0, 8.0, 7.0])
    results = [percentile(values, p) for p in (0, 25, 50, 75, 90, 95, 99, 100)]
    assert results == sorted(results)
