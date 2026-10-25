"""HTTP control API for fault injection against the running turbine simulator.

This is deliberately separate from the Modbus TCP server: Modbus here is
read-only telemetry (the collector never writes a register), and fault
injection is an out-of-band test-harness concern, not something a real SCADA
collector would ever be able to do to a turbine.
"""

from __future__ import annotations

from dataclasses import asdict

from aiohttp import web

from windfarm.simulator.faults import fault_type_from_name
from windfarm.simulator.turbine import TurbineState

DEFAULT_FAULT_DURATION_S = 30.0


def _readout_json(state: TurbineState) -> dict:
    readout = asdict(state.readout())
    readout["status"] = readout["status"].name if hasattr(readout["status"], "name") else readout["status"]
    return readout


def build_control_app(turbine_states: dict[int, TurbineState]) -> web.Application:
    app = web.Application()
    app["turbine_states"] = turbine_states

    async def healthz(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "turbine_count": len(turbine_states)})

    async def list_turbines(_request: web.Request) -> web.Response:
        return web.json_response([_readout_json(s) for s in turbine_states.values()])

    async def get_turbine(request: web.Request) -> web.Response:
        state = _resolve_turbine(request)
        return web.json_response(_readout_json(state))

    async def inject_fault(request: web.Request) -> web.Response:
        state = _resolve_turbine(request)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        fault_name = body.get("type")
        if not fault_name:
            raise web.HTTPBadRequest(text='missing required field "type"')
        try:
            fault_type = fault_type_from_name(fault_name)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        duration_s = body.get("duration_s", DEFAULT_FAULT_DURATION_S)
        if duration_s is not None and (not isinstance(duration_s, (int, float)) or duration_s <= 0):
            raise web.HTTPBadRequest(text="duration_s must be a positive number, or null for indefinite")
        state.inject_fault(fault_type, duration_s)
        return web.json_response(_readout_json(state))

    async def clear_fault(request: web.Request) -> web.Response:
        state = _resolve_turbine(request)
        state.clear_fault()
        return web.json_response(_readout_json(state))

    def _resolve_turbine(request: web.Request) -> TurbineState:
        try:
            turbine_id = int(request.match_info["turbine_id"])
        except ValueError as exc:
            raise web.HTTPBadRequest(text="turbine_id must be an integer") from exc
        state = turbine_states.get(turbine_id)
        if state is None:
            raise web.HTTPNotFound(text=f"no such turbine: {turbine_id}")
        return state

    app.add_routes(
        [
            web.get("/healthz", healthz),
            web.get("/turbines", list_turbines),
            web.get("/turbines/{turbine_id}", get_turbine),
            web.post("/turbines/{turbine_id}/faults", inject_fault),
            web.delete("/turbines/{turbine_id}/faults", clear_fault),
        ]
    )
    return app
