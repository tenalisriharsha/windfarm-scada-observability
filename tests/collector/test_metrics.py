from prometheus_client import CollectorRegistry, generate_latest

from windfarm.collector.metrics import build_metrics


def test_build_metrics_registers_expected_series_names():
    registry = CollectorRegistry()
    metrics = build_metrics(registry)

    metrics.up.labels(turbine_id="1").set(1)
    metrics.last_seen_age_seconds.labels(turbine_id="1").set(0.5)
    metrics.rotor_speed_rpm.labels(turbine_id="1").set(17.2)
    metrics.power_output_kw.labels(turbine_id="1").set(1800.0)
    metrics.wind_speed_mps.labels(turbine_id="1").set(10.1)
    metrics.gearbox_temp_celsius.labels(turbine_id="1").set(61.3)
    metrics.status_code.labels(turbine_id="1").set(0)
    metrics.poll_duration_seconds.labels(turbine_id="1").observe(0.05)
    metrics.poll_attempts_total.labels(turbine_id="1", outcome="success").inc()

    output = generate_latest(registry).decode()
    for expected in [
        "windfarm_turbine_up",
        "windfarm_turbine_last_seen_age_seconds",
        "windfarm_turbine_rotor_speed_rpm",
        "windfarm_turbine_power_output_kw",
        "windfarm_turbine_wind_speed_mps",
        "windfarm_turbine_gearbox_temp_celsius",
        "windfarm_turbine_status_code",
        "windfarm_collector_poll_duration_seconds",
        "windfarm_collector_poll_attempts_total",
    ]:
        assert expected in output


def test_separate_registries_do_not_collide():
    # A regression guard: building metrics twice against fresh registries
    # must not raise prometheus_client's duplicate-timeseries error.
    build_metrics(CollectorRegistry())
    build_metrics(CollectorRegistry())
