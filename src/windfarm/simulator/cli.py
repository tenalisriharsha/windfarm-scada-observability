"""Entrypoint: run N simulated turbines over Modbus TCP plus an HTTP control API.

    python -m windfarm.simulator.cli --turbines 5 --modbus-port 5020 --control-port 8080
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random

from aiohttp import web

from windfarm.simulator.control_api import build_control_app
from windfarm.simulator.modbus_server import (
    build_server_context,
    run_modbus_server,
    run_physics_loop,
)
from windfarm.simulator.turbine import TurbineConfig, TurbineState

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turbines", type=int, default=5, help="number of simulated turbines (default: 5)")
    parser.add_argument("--modbus-host", default="0.0.0.0", help="Modbus TCP bind address")
    parser.add_argument("--modbus-port", type=int, default=5020, help="Modbus TCP bind port")
    parser.add_argument("--control-host", default="0.0.0.0", help="fault-injection HTTP API bind address")
    parser.add_argument("--control-port", type=int, default=8080, help="fault-injection HTTP API bind port")
    parser.add_argument("--tick-interval", type=float, default=1.0, help="physics tick interval in seconds")
    parser.add_argument("--seed", type=int, default=None, help="random seed for reproducible simulation")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def build_turbine_states(count: int, seed: int | None) -> dict[int, TurbineState]:
    states = {}
    for turbine_id in range(1, count + 1):
        rng = random.Random(f"{seed}:{turbine_id}") if seed is not None else None
        states[turbine_id] = TurbineState(TurbineConfig(turbine_id=turbine_id), rng=rng)
    return states


async def run(args: argparse.Namespace) -> None:
    turbine_states = build_turbine_states(args.turbines, args.seed)
    server_context, slave_contexts = build_server_context(turbine_states)

    control_app = build_control_app(turbine_states)
    runner = web.AppRunner(control_app)
    await runner.setup()
    site = web.TCPSite(runner, args.control_host, args.control_port)
    await site.start()
    logger.info("control api listening on %s:%d", args.control_host, args.control_port)

    try:
        await asyncio.gather(
            run_physics_loop(turbine_states, slave_contexts, args.tick_interval),
            run_modbus_server(args.modbus_host, args.modbus_port, server_context),
        )
    finally:
        await runner.cleanup()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        logger.info("shutting down")


if __name__ == "__main__":
    main()
