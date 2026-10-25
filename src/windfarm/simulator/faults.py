"""Fault injection types for the turbine simulator."""

from __future__ import annotations

from dataclasses import dataclass

from windfarm.common.status import FAULT_NAME_TO_TYPE, FaultType


@dataclass
class ActiveFault:
    """A fault currently in effect on a turbine.

    ``expires_at`` is a monotonic timestamp; ``None`` means the fault stays
    active until explicitly cleared (e.g. via the control API).
    """

    fault_type: FaultType
    started_at: float
    expires_at: float | None

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and now >= self.expires_at


def fault_type_from_name(name: str) -> FaultType:
    """Resolve a fault type from a user-supplied string (CLI flag or JSON body)."""
    key = name.strip().lower()
    try:
        return FAULT_NAME_TO_TYPE[key]
    except KeyError as exc:
        valid = ", ".join(sorted(FAULT_NAME_TO_TYPE))
        raise ValueError(f"unknown fault type {name!r}; valid types: {valid}") from exc
