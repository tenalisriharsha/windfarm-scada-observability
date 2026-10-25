"""Collector configuration: which turbines to poll, and how forgiving to be."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TurbineTarget:
    """One turbine the collector polls, addressed by host/port/Modbus unit id."""

    turbine_id: int
    host: str
    port: int
    unit_id: int


@dataclass(frozen=True)
class CollectorConfig:
    """Tunables for polling behaviour. Defaults favor a responsive local demo."""

    targets: tuple[TurbineTarget, ...]
    poll_interval_s: float = 5.0
    request_timeout_s: float = 2.0
    max_retries: int = 3
    backoff_base_s: float = 0.5
    backoff_max_s: float = 5.0
    stale_after_s: float = 15.0
    staleness_refresh_interval_s: float = 1.0


def single_gateway_targets(turbine_ids: list[int], host: str, port: int) -> tuple[TurbineTarget, ...]:
    """Build targets for turbines multiplexed behind one Modbus TCP gateway by unit id.

    This matches the simulator's own addressing scheme: one TCP endpoint,
    one Modbus unit id per turbine.
    """
    return tuple(TurbineTarget(turbine_id=tid, host=host, port=port, unit_id=tid) for tid in turbine_ids)
