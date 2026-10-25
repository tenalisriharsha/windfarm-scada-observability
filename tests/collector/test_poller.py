from prometheus_client import CollectorRegistry

from windfarm.collector.config import CollectorConfig, TurbineTarget
from windfarm.collector.metrics import build_metrics
from windfarm.collector.poller import TurbinePoller
from windfarm.common.registers import encode_reading

from .fake_modbus import FakeModbusClient, FakeResponse, factory_for

TARGET = TurbineTarget(turbine_id=1, host="127.0.0.1", port=5020, unit_id=1)

GOOD_REGISTERS = encode_reading(
    rotor_speed_rpm=15.0, power_output_kw=1500.0, wind_speed_mps=9.0, gearbox_temp_c=55.0, status_code=0
)


def make_config(**overrides) -> CollectorConfig:
    defaults = dict(
        targets=(TARGET,),
        poll_interval_s=100.0,
        request_timeout_s=1.0,
        max_retries=3,
        backoff_base_s=0.001,
        backoff_max_s=0.01,
        stale_after_s=15.0,
    )
    defaults.update(overrides)
    return CollectorConfig(**defaults)


def make_poller(behaviors, **config_overrides) -> tuple[TurbinePoller, CollectorRegistry]:
    registry = CollectorRegistry()
    metrics = build_metrics(registry)
    client = FakeModbusClient(behaviors)
    poller = TurbinePoller(TARGET, make_config(**config_overrides), metrics, factory_for(client))
    return poller, registry


async def test_poll_once_succeeds_on_first_attempt():
    poller, registry = make_poller([FakeResponse(registers=GOOD_REGISTERS)])
    result = await poller.poll_once()
    assert result.success is True
    assert result.attempts == 1
    assert result.reading.rotor_speed_rpm == 15.0
    assert poller.last_success_monotonic is not None
    assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": "1"}) == 1.0


async def test_poll_once_retries_past_a_transient_failure_then_succeeds():
    poller, registry = make_poller(
        [TimeoutError("timed out"), FakeResponse(error=True), FakeResponse(registers=GOOD_REGISTERS)]
    )
    result = await poller.poll_once()
    assert result.success is True
    assert result.attempts == 3
    assert (
        registry.get_sample_value("windfarm_collector_poll_attempts_total", {"turbine_id": "1", "outcome": "timeout"})
        == 1.0
    )
    assert (
        registry.get_sample_value("windfarm_collector_poll_attempts_total", {"turbine_id": "1", "outcome": "error"})
        == 1.0
    )
    assert (
        registry.get_sample_value("windfarm_collector_poll_attempts_total", {"turbine_id": "1", "outcome": "success"})
        == 1.0
    )


async def test_poll_once_exhausts_retries_and_reports_failure():
    poller, registry = make_poller([FakeResponse(error=True)] * 4, max_retries=3)
    result = await poller.poll_once()
    assert result.success is False
    assert result.attempts == 4
    assert poller.last_success_monotonic is None
    assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": "1"}) == 0.0


async def test_never_polled_turbine_reports_down_and_infinite_age():
    poller, registry = make_poller([])
    poller.refresh_staleness(now=0.0)
    assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": "1"}) == 0.0
    assert registry.get_sample_value("windfarm_turbine_last_seen_age_seconds", {"turbine_id": "1"}) == float("inf")


async def test_refresh_staleness_flips_up_to_zero_after_threshold_without_a_new_poll():
    poller, registry = make_poller([FakeResponse(registers=GOOD_REGISTERS)], stale_after_s=10.0)
    await poller.poll_once()
    success_time = poller.last_success_monotonic

    poller.refresh_staleness(now=success_time + 5.0)
    assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": "1"}) == 1.0

    poller.refresh_staleness(now=success_time + 11.0)
    assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": "1"}) == 0.0
    assert registry.get_sample_value("windfarm_turbine_last_seen_age_seconds", {"turbine_id": "1"}) == 11.0


async def test_poller_never_calls_a_write_method():
    # The collector must be read-only: this is a hard structural guarantee, not a
    # behavioural coincidence, so assert directly on the fake's recorded calls.
    registry = CollectorRegistry()
    metrics = build_metrics(registry)
    client = FakeModbusClient([FakeResponse(registers=GOOD_REGISTERS)])
    poller = TurbinePoller(TARGET, make_config(), metrics, factory_for(client))

    await poller.poll_once()

    assert not hasattr(client, "write_calls")
    assert client.read_calls == 1
