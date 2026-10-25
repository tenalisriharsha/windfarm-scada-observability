"""Shared Modbus holding-register map for a single turbine.

Both the simulator (server side) and the collector (client side) import this
module so the register layout only exists in one place. Addresses below are
0-based, as seen by a Modbus client issuing ``read_holding_registers``.

Each turbine is addressed by its own Modbus unit/device id and exposes the
same 5 holding registers starting at address 0. All values are scaled into
16-bit unsigned integers since Modbus holding registers are 16 bits wide.
"""

from __future__ import annotations

from dataclasses import dataclass

ADDR_ROTOR_SPEED_RPM_X10 = 0
ADDR_POWER_OUTPUT_KW_X10 = 1
ADDR_WIND_SPEED_MPS_X100 = 2
ADDR_GEARBOX_TEMP_C_X10 = 3
ADDR_STATUS_CODE = 4

REGISTER_COUNT = 5

# Scale factors used to pack each floating-point reading into an integer
# register. Chosen so the realistic operating range of a turbine (including
# fault extremes) stays well under the uint16 ceiling of 65535.
ROTOR_SPEED_SCALE = 10.0
POWER_OUTPUT_SCALE = 10.0
WIND_SPEED_SCALE = 100.0
GEARBOX_TEMP_SCALE = 10.0

UINT16_MAX = 0xFFFF


def _clamp_u16(value: int) -> int:
    return max(0, min(UINT16_MAX, value))


@dataclass(frozen=True)
class TurbineReading:
    """A decoded snapshot of one turbine's holding registers."""

    rotor_speed_rpm: float
    power_output_kw: float
    wind_speed_mps: float
    gearbox_temp_c: float
    status_code: int


def encode_reading(
    *,
    rotor_speed_rpm: float,
    power_output_kw: float,
    wind_speed_mps: float,
    gearbox_temp_c: float,
    status_code: int,
) -> list[int]:
    """Pack turbine readings into the 5-register holding-register block."""
    return [
        _clamp_u16(round(rotor_speed_rpm * ROTOR_SPEED_SCALE)),
        _clamp_u16(round(power_output_kw * POWER_OUTPUT_SCALE)),
        _clamp_u16(round(wind_speed_mps * WIND_SPEED_SCALE)),
        _clamp_u16(round(gearbox_temp_c * GEARBOX_TEMP_SCALE)),
        _clamp_u16(status_code),
    ]


def decode_reading(registers: list[int]) -> TurbineReading:
    """Unpack a 5-register holding-register block into turbine readings."""
    if len(registers) != REGISTER_COUNT:
        raise ValueError(f"expected {REGISTER_COUNT} registers, got {len(registers)}")
    return TurbineReading(
        rotor_speed_rpm=registers[ADDR_ROTOR_SPEED_RPM_X10] / ROTOR_SPEED_SCALE,
        power_output_kw=registers[ADDR_POWER_OUTPUT_KW_X10] / POWER_OUTPUT_SCALE,
        wind_speed_mps=registers[ADDR_WIND_SPEED_MPS_X100] / WIND_SPEED_SCALE,
        gearbox_temp_c=registers[ADDR_GEARBOX_TEMP_C_X10] / GEARBOX_TEMP_SCALE,
        status_code=registers[ADDR_STATUS_CODE],
    )
