"""End-to-end test: a real simulator Modbus server polled by a real collector poller.

Unlike the unit tests elsewhere (which fake the Modbus client), this spins up
an actual pymodbus TCP server backed by the simulator's physics loop, and
drives it with the collector's real ``TurbinePoller`` -- including letting a
comm-loss fault produce a genuine client-side timeout.
"""

from __future__ import annotations

import asyncio
import random
import socket

import pytest
from prometheus_client import CollectorRegistry

from windfarm.collector.config import CollectorConfig, TurbineTarget
from windfarm.collector.metrics import build_metrics
from windfarm.collector.poller import TurbinePoller
from windfarm.common.status import FaultType
from windfarm.simulator.modbus_server import build_server_context, run_modbus_server, run_physics_loop
from windfarm.simulator.turbine import TurbineConfig, TurbineState


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def running_simulator():
    port = _free_tcp_port()
    states = {1: TurbineState(TurbineConfig(turbine_id=1), rng=random.Random(1))}
    context, slave_contexts = build_server_context(states)

    server_task = asyncio.create_task(run_modbus_server("127.0.0.1", port, context))
    physics_task = asyncio.create_task(run_physics_loop(states, slave_contexts, tick_interval_s=0.05))
    await asyncio.sleep(0.3)  # let the server bind and a few physics ticks run

    try:
        yield states, port
    finally:
        server_task.cancel()
        physics_task.cancel()
        await asyncio.gather(server_task, physics_task, return_exceptions=True)


def _make_poller(port: int, stale_after_s: float = 5.0) -> tuple[TurbinePoller, CollectorRegistry]:
    target = TurbineTarget(turbine_id=1, host="127.0.0.1", port=port, unit_id=1)
    config = CollectorConfig(
        targets=(target,),
        request_timeout_s=0.3,
        max_retries=1,
        backoff_base_s=0.05,
        backoff_max_s=0.1,
        stale_after_s=stale_after_s,
    )
    registry = CollectorRegistry()
    metrics = build_metrics(registry)
    return TurbinePoller(target, config, metrics), registry


async def test_poller_reads_live_simulator_telemetry(running_simulator):
    _states, port = running_simulator
    poller, _registry = _make_poller(port)

    result = await poller.poll_once()

    assert result.success is True
    assert result.reading is not None
    assert 0.0 <= result.reading.rotor_speed_rpm <= 20.0
    assert result.reading.status_code == 0
    await poller.close()


async def test_overheating_fault_is_visible_in_polled_reading(running_simulator):
    states, port = running_simulator
    poller, _registry = _make_poller(port)

    states[1].inject_fault(FaultType.OVERHEATING, duration_s=5.0)
    await asyncio.sleep(0.2)

    result = await poller.poll_once()

    assert result.success is True
    assert result.reading.gearbox_temp_c >= 120.0
    assert result.reading.status_code == 3  # FAULT_OVERHEAT
    await poller.close()


async def test_comm_loss_fault_causes_poll_failure(running_simulator):
    states, port = running_simulator
    # up is debounced by stale_after_s (see test_poller.py) rather than flapping on
    # every single missed poll, so use a short threshold to observe the flip quickly.
    poller, registry = _make_poller(port, stale_after_s=0.05)

    assert (await poller.poll_once()).success is True

    states[1].inject_fault(FaultType.COMM_LOSS, duration_s=5.0)
    await asyncio.sleep(0.2)

    result = await poller.poll_once()

    assert result.success is False
    assert registry.get_sample_value("windfarm_turbine_up", {"turbine_id": "1"}) == 0.0
    await poller.close()
