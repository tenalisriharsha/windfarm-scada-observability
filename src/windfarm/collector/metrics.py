"""Prometheus metric definitions for the collector.

Metrics are built against an explicit registry (via :func:`build_metrics`)
rather than the implicit global default, so tests can use a fresh
``CollectorRegistry`` per test without colliding on already-registered
metric names. The CLI entrypoint binds to ``prometheus_client.REGISTRY`` so
``start_http_server`` serves the real thing.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import Counter, CollectorRegistry, Gauge, Histogram

NAMESPACE = "windfarm"


@dataclass(frozen=True)
class Metrics:
    up: Gauge
    last_seen_age_seconds: Gauge
    rotor_speed_rpm: Gauge
    power_output_kw: Gauge
    wind_speed_mps: Gauge
    gearbox_temp_celsius: Gauge
    status_code: Gauge
    poll_duration_seconds: Histogram
    poll_attempts_total: Counter


def build_metrics(registry: CollectorRegistry) -> Metrics:
    labels = ["turbine_id"]
    return Metrics(
        up=Gauge(
            f"{NAMESPACE}_turbine_up",
            "1 if the most recent poll of this turbine succeeded, else 0",
            labels,
            registry=registry,
        ),
        last_seen_age_seconds=Gauge(
            f"{NAMESPACE}_turbine_last_seen_age_seconds",
            "Seconds since the last successful poll of this turbine",
            labels,
            registry=registry,
        ),
        rotor_speed_rpm=Gauge(
            f"{NAMESPACE}_turbine_rotor_speed_rpm",
            "Last-reported rotor speed in rpm",
            labels,
            registry=registry,
        ),
        power_output_kw=Gauge(
            f"{NAMESPACE}_turbine_power_output_kw",
            "Last-reported power output in kW",
            labels,
            registry=registry,
        ),
        wind_speed_mps=Gauge(
            f"{NAMESPACE}_turbine_wind_speed_mps",
            "Last-reported wind speed in m/s",
            labels,
            registry=registry,
        ),
        gearbox_temp_celsius=Gauge(
            f"{NAMESPACE}_turbine_gearbox_temp_celsius",
            "Last-reported gearbox temperature in Celsius",
            labels,
            registry=registry,
        ),
        status_code=Gauge(
            f"{NAMESPACE}_turbine_status_code",
            "Last-reported turbine status code (see windfarm.common.status.TurbineStatus)",
            labels,
            registry=registry,
        ),
        poll_duration_seconds=Histogram(
            f"{NAMESPACE}_collector_poll_duration_seconds",
            "Time spent polling a turbine, including retries",
            labels,
            registry=registry,
        ),
        poll_attempts_total=Counter(
            f"{NAMESPACE}_collector_poll_attempts_total",
            "Poll attempts by outcome",
            labels + ["outcome"],
            registry=registry,
        ),
    )
