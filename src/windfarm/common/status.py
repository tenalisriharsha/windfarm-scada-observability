"""Turbine status codes and fault types shared by the simulator and collector."""

from __future__ import annotations

from enum import IntEnum


class TurbineStatus(IntEnum):
    """Value carried in the status-code holding register."""

    OK = 0
    WARNING = 1
    FAULT_OVERSPEED = 2
    FAULT_OVERHEAT = 3


class FaultType(IntEnum):
    """Fault types injectable via the simulator's control API/CLI.

    COMM_LOSS is handled at the transport layer (the simulator stops
    responding on Modbus for the affected turbine) rather than as a
    status-register value, since a real comms fault means the device
    cannot report its own status.
    """

    OVERSPEED = 0
    OVERHEATING = 1
    COMM_LOSS = 2


FAULT_NAME_TO_TYPE = {fault.name.lower(): fault for fault in FaultType}
