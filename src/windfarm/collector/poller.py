"""Async, read-only polling of a single turbine over Modbus TCP.

The collector never writes a Modbus register: only ``read_holding_registers``
is ever called. Each attempt gets its own timeout (via the client's
``timeout=``), pymodbus's own built-in retry is disabled (``retries=0``) so
this module's retry-with-backoff loop is the single source of retry
behaviour, and every outcome -- success, timeout, or error response -- is
recorded as a Prometheus metric.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from windfarm.collector import stale
from windfarm.collector.config import CollectorConfig, TurbineTarget
from windfarm.collector.metrics import Metrics
from windfarm.common.registers import REGISTER_COUNT, TurbineReading, decode_reading

logger = logging.getLogger(__name__)

ClientFactory = Callable[[TurbineTarget, float], AsyncModbusTcpClient]


def default_client_factory(target: TurbineTarget, timeout_s: float) -> AsyncModbusTcpClient:
    return AsyncModbusTcpClient(target.host, port=target.port, timeout=timeout_s, retries=0)


@dataclass(frozen=True)
class PollResult:
    success: bool
    reading: TurbineReading | None
    attempts: int
    duration_s: float
    error: str | None


class TurbinePoller:
    """Polls one turbine, tracking last-success time for staleness detection."""

    def __init__(
        self,
        target: TurbineTarget,
        config: CollectorConfig,
        metrics: Metrics,
        client_factory: ClientFactory = default_client_factory,
    ) -> None:
        self.target = target
        self.config = config
        self.metrics = metrics
        self._client_factory = client_factory
        self._client: AsyncModbusTcpClient | None = None
        self.last_success_monotonic: float | None = None

    def _ensure_client(self):
        # pymodbus's AsyncModbusTcpClient needs a running event loop at
        # construction time, so it can't be built in __init__: the collector
        # CLI constructs pollers before calling asyncio.run(). Building it
        # lazily on first use (always inside an awaited coroutine) avoids
        # a "no running event loop" RuntimeError.
        if self._client is None:
            self._client = self._client_factory(self.target, self.config.request_timeout_s)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _label(self) -> str:
        return str(self.target.turbine_id)

    async def poll_once(self) -> PollResult:
        start = time.monotonic()
        last_error: Exception | None = None
        client = self._ensure_client()

        for attempt in range(self.config.max_retries + 1):
            try:
                if not client.connected:
                    if not await client.connect():
                        raise ConnectionError(f"could not connect to {self.target.host}:{self.target.port}")
                response = await client.read_holding_registers(
                    address=0, count=REGISTER_COUNT, slave=self.target.unit_id
                )
                if response.isError():
                    raise ModbusException(str(response))

                reading = decode_reading(list(response.registers))
                duration = time.monotonic() - start
                self.last_success_monotonic = time.monotonic()
                self._record_attempt("success")
                self._record_reading(reading)
                self.metrics.poll_duration_seconds.labels(turbine_id=self._label()).observe(duration)
                return PollResult(success=True, reading=reading, attempts=attempt + 1, duration_s=duration, error=None)
            except Exception as exc:  # noqa: BLE001 - unify timeouts/IO/protocol errors into one retry path
                last_error = exc
                self._record_attempt("timeout" if _looks_like_timeout(exc) else "error")
                if attempt < self.config.max_retries:
                    backoff = min(self.config.backoff_max_s, self.config.backoff_base_s * (2**attempt))
                    await self._sleep(backoff)

        duration = time.monotonic() - start
        self.metrics.poll_duration_seconds.labels(turbine_id=self._label()).observe(duration)
        self._refresh_up_and_age()
        logger.warning("turbine %s poll failed after %d attempt(s): %s", self.target.turbine_id, self.config.max_retries + 1, last_error)
        return PollResult(success=False, reading=None, attempts=self.config.max_retries + 1, duration_s=duration, error=str(last_error))

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def _record_attempt(self, outcome: str) -> None:
        self.metrics.poll_attempts_total.labels(turbine_id=self._label(), outcome=outcome).inc()

    def _record_reading(self, reading: TurbineReading) -> None:
        label = self._label()
        self.metrics.rotor_speed_rpm.labels(turbine_id=label).set(reading.rotor_speed_rpm)
        self.metrics.power_output_kw.labels(turbine_id=label).set(reading.power_output_kw)
        self.metrics.wind_speed_mps.labels(turbine_id=label).set(reading.wind_speed_mps)
        self.metrics.gearbox_temp_celsius.labels(turbine_id=label).set(reading.gearbox_temp_c)
        self.metrics.status_code.labels(turbine_id=label).set(reading.status_code)
        self._refresh_up_and_age()

    def refresh_staleness(self, now: float | None = None) -> None:
        """Recompute up/last-seen-age independent of any poll attempt completing."""
        self._refresh_up_and_age(now)

    def _refresh_up_and_age(self, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        age = stale.seen_age(self.last_success_monotonic, now)
        label = self._label()
        self.metrics.last_seen_age_seconds.labels(turbine_id=label).set(age)
        up = 0 if stale.is_stale(self.last_success_monotonic, now, self.config.stale_after_s) else 1
        self.metrics.up.labels(turbine_id=label).set(up)


def _looks_like_timeout(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    return "no response received" in str(exc).lower()
