import asyncio

from prometheus_client import CollectorRegistry

from windfarm.collector.config import CollectorConfig, TurbineTarget
from windfarm.collector.metrics import build_metrics
from windfarm.collector.service import Collector
from windfarm.common.registers import encode_reading

from .fake_modbus import FakeModbusClient, FakeResponse, factory_for

GOOD_REGISTERS = encode_reading(
    rotor_speed_rpm=12.0, power_output_kw=900.0, wind_speed_mps=7.0, gearbox_temp_c=48.0, status_code=0
)


async def test_collector_polls_every_configured_target_repeatedly():
    targets = (
        TurbineTarget(turbine_id=1, host="h", port=1, unit_id=1),
        TurbineTarget(turbine_id=2, host="h", port=1, unit_id=2),
    )
    config = CollectorConfig(
        targets=targets,
        poll_interval_s=0.02,
        request_timeout_s=0.5,
        max_retries=0,
        stale_after_s=5.0,
        staleness_refresh_interval_s=0.02,
    )
    registry = CollectorRegistry()
    metrics = build_metrics(registry)

    clients = {t.turbine_id: FakeModbusClient([FakeResponse(registers=GOOD_REGISTERS)] * 50) for t in targets}

    def client_factory(target, _timeout_s):
        return clients[target.turbine_id]

    collector = Collector(config, metrics, client_factory)
    task = asyncio.create_task(collector.run_forever())
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    for turbine_id in (1, 2):
        assert clients[turbine_id].read_calls >= 2
        assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": str(turbine_id)}) == 1.0


async def test_collector_keeps_polling_other_turbines_when_one_errors_every_time():
    targets = (
        TurbineTarget(turbine_id=1, host="h", port=1, unit_id=1),
        TurbineTarget(turbine_id=2, host="h", port=1, unit_id=2),
    )
    config = CollectorConfig(
        targets=targets,
        poll_interval_s=0.02,
        request_timeout_s=0.3,
        max_retries=0,
        backoff_base_s=0.001,
        stale_after_s=5.0,
        staleness_refresh_interval_s=0.02,
    )
    registry = CollectorRegistry()
    metrics = build_metrics(registry)

    clients = {
        1: FakeModbusClient([FakeResponse(error=True)] * 50),
        2: FakeModbusClient([FakeResponse(registers=GOOD_REGISTERS)] * 50),
    }

    def client_factory(target, _timeout_s):
        return clients[target.turbine_id]

    collector = Collector(config, metrics, client_factory)
    task = asyncio.create_task(collector.run_forever())
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": "1"}) == 0.0
    assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": "2"}) == 1.0
