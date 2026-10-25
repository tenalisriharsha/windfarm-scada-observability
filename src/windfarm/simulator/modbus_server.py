"""Modbus TCP server wiring: one gateway, many turbines addressed by unit id.

pymodbus 3.8.6 requires each ``ModbusSequentialDataBlock`` to be constructed
with a starting address of 1, because ``ModbusSlaveContext.validate`` always
adds 1 to the address a client sent before checking it against the block's
own range (a long-standing pymodbus quirk, verified against this exact
version). Holding register 0 as seen by a client therefore lives at index 1
of the backing block below.
"""

from __future__ import annotations

import asyncio
import logging

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.exceptions import NoSuchSlaveException
from pymodbus.server import StartAsyncTcpServer

from windfarm.common.registers import REGISTER_COUNT
from windfarm.simulator.turbine import TurbineState

logger = logging.getLogger(__name__)

DATABLOCK_START_ADDRESS = 1


class TurbineSlaveContext(ModbusSlaveContext):
    """A per-turbine Modbus datastore that can simulate a dead link.

    Values are pushed into the backing holding-register block by the
    simulator's physics tick loop (see :func:`run_physics_loop`), not read
    live on each Modbus request. While ``state.comm_loss`` is set, reads
    raise :class:`NoSuchSlaveException`, which (combined with
    ``ignore_missing_slaves=True`` on the server) makes pymodbus send no
    response at all -- a real client-side timeout, just as a real turbine
    gateway going silent would look.
    """

    def __init__(self, state: TurbineState) -> None:
        super().__init__(hr=ModbusSequentialDataBlock(DATABLOCK_START_ADDRESS, [0] * REGISTER_COUNT))
        self.state = state

    def getValues(self, fc_as_hex: int, address: int, count: int = 1):
        if self.state.comm_loss:
            raise NoSuchSlaveException(f"turbine {self.state.config.turbine_id} comm loss (simulated)")
        return super().getValues(fc_as_hex, address, count)


def build_server_context(turbine_states: dict[int, TurbineState]) -> tuple[ModbusServerContext, dict[int, TurbineSlaveContext]]:
    """Build a multi-device server context keyed by turbine id (== Modbus unit id)."""
    slave_contexts = {turbine_id: TurbineSlaveContext(state) for turbine_id, state in turbine_states.items()}
    server_context = ModbusServerContext(slaves=slave_contexts, single=False)
    return server_context, slave_contexts


async def run_physics_loop(
    turbine_states: dict[int, TurbineState],
    slave_contexts: dict[int, TurbineSlaveContext],
    tick_interval_s: float,
) -> None:
    """Advance every turbine's physics and push the result into its datastore, forever."""
    while True:
        for turbine_id, state in turbine_states.items():
            state.tick(tick_interval_s)
            slave_contexts[turbine_id].setValues(3, 0, state.registers_snapshot())
        await asyncio.sleep(tick_interval_s)


async def run_modbus_server(host: str, port: int, server_context: ModbusServerContext) -> None:
    """Run the Modbus TCP server until cancelled."""
    logger.info("starting modbus tcp server on %s:%d", host, port)
    await StartAsyncTcpServer(
        context=server_context,
        address=(host, port),
        ignore_missing_slaves=True,
    )
