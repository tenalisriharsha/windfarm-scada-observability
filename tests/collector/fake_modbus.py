"""A minimal fake standing in for pymodbus's AsyncModbusTcpClient, for poller tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeResponse:
    registers: list[int] | None = None
    error: bool = False

    def isError(self) -> bool:
        return self.error


class FakeModbusClient:
    """Replays a scripted sequence of responses/exceptions, one per read call."""

    def __init__(self, behaviors: list):
        self._behaviors = list(behaviors)
        self.connected = False
        self.read_calls = 0
        self.closed = False

    async def connect(self) -> bool:
        self.connected = True
        return True

    def close(self) -> None:
        self.connected = False
        self.closed = True

    async def read_holding_registers(self, *, address: int, count: int, slave: int):
        self.read_calls += 1
        if not self._behaviors:
            raise AssertionError("FakeModbusClient ran out of scripted behaviors")
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def factory_for(client: FakeModbusClient):
    def _factory(_target, _timeout_s):
        return client

    return _factory
