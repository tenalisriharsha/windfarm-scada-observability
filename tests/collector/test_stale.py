import math

from windfarm.collector.stale import is_stale, seen_age


def test_seen_age_is_infinite_when_never_successful():
    assert seen_age(None, now_monotonic=100.0) == math.inf


def test_seen_age_computes_elapsed_time():
    assert seen_age(last_success_monotonic=10.0, now_monotonic=13.5) == 3.5


def test_seen_age_never_negative():
    assert seen_age(last_success_monotonic=10.0, now_monotonic=9.0) == 0.0


def test_is_stale_true_when_never_seen():
    assert is_stale(None, now_monotonic=0.0, threshold_s=15.0) is True


def test_is_stale_false_within_threshold():
    assert is_stale(last_success_monotonic=0.0, now_monotonic=10.0, threshold_s=15.0) is False


def test_is_stale_true_past_threshold():
    assert is_stale(last_success_monotonic=0.0, now_monotonic=15.1, threshold_s=15.0) is True


def test_is_stale_boundary_is_exclusive():
    assert is_stale(last_success_monotonic=0.0, now_monotonic=15.0, threshold_s=15.0) is False
