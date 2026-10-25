import random

from windfarm.common.status import FaultType, TurbineStatus
from windfarm.simulator.turbine import TurbineConfig, TurbineState


def make_state(turbine_id: int = 1, seed: int = 1) -> TurbineState:
    return TurbineState(TurbineConfig(turbine_id=turbine_id), rng=random.Random(seed))


def test_fresh_turbine_starts_in_ok_status_with_no_fault():
    state = make_state()
    assert state.status == TurbineStatus.OK
    assert state.active_fault is None
    assert state.comm_loss is False


def test_tick_keeps_readings_within_physical_bounds():
    state = make_state()
    for _ in range(200):
        state.tick(dt=1.0)
        assert 0.0 <= state.wind_speed_mps <= state.config.cut_out_wind_mps + 5.0
        assert 0.0 <= state.rotor_speed_rpm <= state.config.rated_rotor_rpm * 1.01
        assert 0.0 <= state.power_output_kw <= state.config.rated_power_kw * 1.01
        assert state.gearbox_temp_c >= 0.0


def test_overspeed_fault_pushes_rotor_speed_past_rated():
    state = make_state()
    state.inject_fault(FaultType.OVERSPEED, duration_s=10.0, now=0.0)
    state.tick(dt=1.0, now=1.0)
    assert state.status == TurbineStatus.FAULT_OVERSPEED
    assert state.rotor_speed_rpm > state.config.rated_rotor_rpm
    assert state.comm_loss is False


def test_overheating_fault_pushes_gearbox_temp_into_fault_range():
    state = make_state()
    state.inject_fault(FaultType.OVERHEATING, duration_s=10.0, now=0.0)
    state.tick(dt=1.0, now=1.0)
    assert state.status == TurbineStatus.FAULT_OVERHEAT
    assert state.gearbox_temp_c >= 130.0


def test_comm_loss_fault_sets_comm_loss_flag_without_forcing_a_status():
    state = make_state()
    state.inject_fault(FaultType.COMM_LOSS, duration_s=10.0, now=0.0)
    state.tick(dt=1.0, now=1.0)
    assert state.comm_loss is True


def test_fault_expires_after_duration():
    state = make_state()
    state.inject_fault(FaultType.OVERSPEED, duration_s=5.0, now=0.0)
    state.tick(dt=1.0, now=3.0)
    assert state.active_fault is not None
    state.tick(dt=1.0, now=6.0)
    assert state.active_fault is None
    assert state.status != TurbineStatus.FAULT_OVERSPEED


def test_clear_fault_resets_comm_loss_immediately():
    state = make_state()
    state.inject_fault(FaultType.COMM_LOSS, duration_s=None, now=0.0)
    state.tick(dt=1.0, now=1.0)
    assert state.comm_loss is True
    state.clear_fault()
    assert state.active_fault is None
    assert state.comm_loss is False


def test_registers_snapshot_round_trips_through_decode():
    from windfarm.common.registers import decode_reading

    state = make_state()
    state.tick(dt=1.0)
    reading = decode_reading(state.registers_snapshot())
    assert reading.status_code == int(state.status)


def test_readout_reports_remaining_fault_duration():
    state = make_state()
    state.inject_fault(FaultType.OVERHEATING, duration_s=10.0, now=0.0)
    readout = state.readout(now=4.0)
    assert readout.active_fault == "overheating"
    assert readout.fault_expires_in_s == 6.0
