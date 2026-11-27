import math

import pytest

from windfarm.simulator.control_api import build_control_app
from windfarm.simulator.turbine import TurbineConfig, TurbineState


def make_states(*ids: int) -> dict[int, TurbineState]:
    return {i: TurbineState(TurbineConfig(turbine_id=i)) for i in ids}


@pytest.fixture
def states():
    return make_states(1, 2)


async def test_healthz_reports_turbine_count(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.get("/healthz")
    assert resp.status == 200
    body = await resp.json()
    assert body == {"status": "ok", "turbine_count": 2}


async def test_list_turbines_returns_all(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.get("/turbines")
    assert resp.status == 200
    body = await resp.json()
    assert {t["turbine_id"] for t in body} == {1, 2}


async def test_get_single_turbine(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.get("/turbines/1")
    assert resp.status == 200
    body = await resp.json()
    assert body["turbine_id"] == 1
    assert body["status"] == "OK"


async def test_get_unknown_turbine_is_404(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.get("/turbines/999")
    assert resp.status == 404


async def test_inject_overspeed_fault(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/1/faults", json={"type": "overspeed", "duration_s": 30})
    assert resp.status == 200
    body = await resp.json()
    assert body["active_fault"] == "overspeed"
    assert states[1].active_fault is not None


async def test_inject_fault_missing_type_is_400(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/1/faults", json={})
    assert resp.status == 400


async def test_inject_fault_unknown_type_is_400(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/1/faults", json={"type": "meltdown"})
    assert resp.status == 400


@pytest.mark.parametrize("fault_name", [5, ["overspeed"], {"a": 1}, True])
async def test_inject_fault_non_string_type_is_400_not_500(aiohttp_client, states, fault_name):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/1/faults", json={"type": fault_name, "duration_s": 10})
    assert resp.status == 400
    assert states[1].active_fault is None


async def test_inject_fault_invalid_duration_is_400(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/1/faults", json={"type": "overspeed", "duration_s": -5})
    assert resp.status == 400


@pytest.mark.parametrize("duration_s", [math.nan, math.inf, -math.inf])
async def test_inject_fault_non_finite_duration_is_400(aiohttp_client, states, duration_s):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/1/faults", json={"type": "overspeed", "duration_s": duration_s})
    assert resp.status == 400
    body = await resp.text()
    assert "duration_s must be a positive number, or null for indefinite" in body
    assert states[1].active_fault is None


async def test_inject_fault_response_never_contains_non_finite_json_tokens(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/1/faults", json={"type": "overspeed", "duration_s": math.inf})
    raw_body = await resp.read()
    assert b"Infinity" not in raw_body
    assert b"NaN" not in raw_body


async def test_inject_fault_on_unknown_turbine_is_404(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/999/faults", json={"type": "overspeed"})
    assert resp.status == 404


async def test_clear_fault(aiohttp_client, states):
    client = await aiohttp_client(build_control_app(states))
    await client.post("/turbines/1/faults", json={"type": "comm_loss"})
    assert states[1].active_fault is not None

    resp = await client.delete("/turbines/1/faults")
    assert resp.status == 200
    assert states[1].active_fault is None
