"""Physics-lite simulation of a single wind turbine's telemetry."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from windfarm.common.registers import encode_reading
from windfarm.common.status import FaultType, TurbineStatus
from windfarm.simulator.faults import ActiveFault

# Fault-override magnitudes, expressed relative to each turbine's own rating
# so the same fault reads sensibly regardless of turbine size.
OVERSPEED_ROTOR_FACTOR = 1.6
OVERSPEED_POWER_FACTOR = 1.3
OVERHEAT_TEMP_MIN_C = 132.0
OVERHEAT_TEMP_MAX_C = 148.0
HIGH_WIND_WARNING_MARGIN_MPS = 1.5

WIND_RANDOM_WALK_STEP_MPS = 0.35
GEARBOX_THERMAL_SMOOTHING = 0.15
GEARBOX_NOISE_C = 0.4


@dataclass(frozen=True)
class TurbineConfig:
    """Static rating plate for a simulated turbine."""

    turbine_id: int
    rated_rotor_rpm: float = 18.0
    rated_power_kw: float = 2000.0
    cut_in_wind_mps: float = 3.0
    rated_wind_mps: float = 12.0
    cut_out_wind_mps: float = 25.0
    rated_gearbox_temp_c: float = 65.0
    ambient_gearbox_temp_c: float = 22.0


@dataclass
class TurbineReadout:
    """A plain snapshot of a turbine's current readings, for the control API."""

    turbine_id: int
    wind_speed_mps: float
    rotor_speed_rpm: float
    power_output_kw: float
    gearbox_temp_c: float
    status: TurbineStatus
    comm_loss: bool
    active_fault: str | None
    fault_expires_in_s: float | None


def _natural_power_fraction(wind_speed_mps: float, config: TurbineConfig) -> float:
    """Simplified cubic wind-turbine power curve, returning a fraction of rated power."""
    if wind_speed_mps < config.cut_in_wind_mps or wind_speed_mps >= config.cut_out_wind_mps:
        return 0.0
    if wind_speed_mps >= config.rated_wind_mps:
        return 1.0
    span = config.rated_wind_mps - config.cut_in_wind_mps
    frac = (wind_speed_mps - config.cut_in_wind_mps) / span
    return max(0.0, min(1.0, frac**3))


class TurbineState:
    """Mutable, tickable simulation state for one turbine."""

    def __init__(self, config: TurbineConfig, rng: random.Random | None = None) -> None:
        self.config = config
        self._rng = rng if rng is not None else random.Random(config.turbine_id)
        self.wind_speed_mps = self._rng.uniform(config.cut_in_wind_mps, config.rated_wind_mps)
        self.rotor_speed_rpm = 0.0
        self.power_output_kw = 0.0
        self.gearbox_temp_c = config.ambient_gearbox_temp_c
        self.status = TurbineStatus.OK
        self.comm_loss = False
        self.active_fault: ActiveFault | None = None

    def inject_fault(self, fault_type: FaultType, duration_s: float | None, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        expires_at = now + duration_s if duration_s is not None else None
        self.active_fault = ActiveFault(fault_type=fault_type, started_at=now, expires_at=expires_at)

    def clear_fault(self) -> None:
        self.active_fault = None
        self.comm_loss = False

    def _clear_expired_fault(self, now: float) -> None:
        if self.active_fault is not None and self.active_fault.is_expired(now):
            self.clear_fault()

    def tick(self, dt: float, now: float | None = None) -> None:
        """Advance the simulation by ``dt`` seconds."""
        now = now if now is not None else time.monotonic()
        self._clear_expired_fault(now)

        self.wind_speed_mps += self._rng.gauss(0.0, WIND_RANDOM_WALK_STEP_MPS)
        self.wind_speed_mps = max(0.0, min(self.config.cut_out_wind_mps + 5.0, self.wind_speed_mps))

        power_fraction = _natural_power_fraction(self.wind_speed_mps, self.config)
        self.power_output_kw = self.config.rated_power_kw * power_fraction
        if self.wind_speed_mps < self.config.cut_in_wind_mps or self.wind_speed_mps >= self.config.cut_out_wind_mps:
            self.rotor_speed_rpm = 0.0
        else:
            speed_fraction = min(1.0, self.wind_speed_mps / self.config.rated_wind_mps)
            self.rotor_speed_rpm = self.config.rated_rotor_rpm * speed_fraction

        target_temp = self.config.ambient_gearbox_temp_c + (
            self.config.rated_gearbox_temp_c - self.config.ambient_gearbox_temp_c
        ) * power_fraction
        self.gearbox_temp_c += (target_temp - self.gearbox_temp_c) * GEARBOX_THERMAL_SMOOTHING
        self.gearbox_temp_c += self._rng.gauss(0.0, GEARBOX_NOISE_C)

        self.comm_loss = False
        if self.active_fault is None:
            near_cutout = self.wind_speed_mps >= self.config.cut_out_wind_mps - HIGH_WIND_WARNING_MARGIN_MPS
            self.status = TurbineStatus.WARNING if near_cutout else TurbineStatus.OK
        elif self.active_fault.fault_type is FaultType.OVERSPEED:
            self.rotor_speed_rpm = self.config.rated_rotor_rpm * OVERSPEED_ROTOR_FACTOR
            self.power_output_kw = self.config.rated_power_kw * OVERSPEED_POWER_FACTOR
            self.status = TurbineStatus.FAULT_OVERSPEED
        elif self.active_fault.fault_type is FaultType.OVERHEATING:
            self.gearbox_temp_c = self._rng.uniform(OVERHEAT_TEMP_MIN_C, OVERHEAT_TEMP_MAX_C)
            self.status = TurbineStatus.FAULT_OVERHEAT
        elif self.active_fault.fault_type is FaultType.COMM_LOSS:
            self.comm_loss = True

    def registers_snapshot(self) -> list[int]:
        return encode_reading(
            rotor_speed_rpm=self.rotor_speed_rpm,
            power_output_kw=self.power_output_kw,
            wind_speed_mps=self.wind_speed_mps,
            gearbox_temp_c=self.gearbox_temp_c,
            status_code=int(self.status),
        )

    def readout(self, now: float | None = None) -> TurbineReadout:
        now = now if now is not None else time.monotonic()
        fault_remaining = None
        fault_name = None
        if self.active_fault is not None:
            fault_name = self.active_fault.fault_type.name.lower()
            if self.active_fault.expires_at is not None:
                fault_remaining = max(0.0, self.active_fault.expires_at - now)
        return TurbineReadout(
            turbine_id=self.config.turbine_id,
            wind_speed_mps=self.wind_speed_mps,
            rotor_speed_rpm=self.rotor_speed_rpm,
            power_output_kw=self.power_output_kw,
            gearbox_temp_c=self.gearbox_temp_c,
            status=self.status,
            comm_loss=self.comm_loss,
            active_fault=fault_name,
            fault_expires_in_s=fault_remaining,
        )
