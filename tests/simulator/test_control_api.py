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


@pytest.mark.parametrize("invalid_duration", [-5, 0, float("nan"), float("inf"), float("-inf"), True])
async def test_inject_fault_invalid_duration_is_400(aiohttp_client, states, invalid_duration):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post("/turbines/1/faults", json={"type": "overspeed", "duration_s": invalid_duration})
    assert resp.status == 400
    text = await resp.text()
    assert "duration_s must be a positive number, or null for indefinite" in text


@pytest.mark.parametrize("raw_token", ["NaN", "Infinity", "-Infinity"])
async def test_inject_fault_raw_non_finite_duration_is_400(aiohttp_client, states, raw_token):
    client = await aiohttp_client(build_control_app(states))
    resp = await client.post(
        "/turbines/1/faults",
        data=f'{{"type": "overspeed", "duration_s": {raw_token}}}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400
    text = await resp.text()
    assert "duration_s must be a positive number, or null for indefinite" in text


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
