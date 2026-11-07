from windfarm.simulator.cli import build_turbine_states
from windfarm.simulator.turbine import TurbineConfig, TurbineState


def test_unseeded_simulator_runs_produce_different_telemetry():
    """Issue #7: Unseeded simulator runs draw OS entropy and produce distinct telemetry."""
    states1 = build_turbine_states(count=1, seed=None)
    states2 = build_turbine_states(count=1, seed=None)

    t1 = states1[1]
    t2 = states2[1]

    for _ in range(10):
        t1.tick(dt=1.0)
        t2.tick(dt=1.0)

    # Telemetry sequences across two unseeded runs must differ
    assert (t1.wind_speed_mps != t2.wind_speed_mps) or (t1.gearbox_temp_c != t2.gearbox_temp_c)


def test_seeded_simulator_runs_produce_identical_telemetry():
    """Seeded simulator runs remain bit-for-bit deterministic."""
    states1 = build_turbine_states(count=1, seed=12345)
    states2 = build_turbine_states(count=1, seed=12345)

    t1 = states1[1]
    t2 = states2[1]

    for _ in range(10):
        t1.tick(dt=1.0)
        t2.tick(dt=1.0)

    assert t1.wind_speed_mps == t2.wind_speed_mps
    assert t1.gearbox_temp_c == t2.gearbox_temp_c
    assert t1.rotor_speed_rpm == t2.rotor_speed_rpm


def test_turbine_state_direct_construction_keeps_deterministic_default():
    """Callers constructing TurbineState directly without rng keep the deterministic default."""
    t1 = TurbineState(TurbineConfig(turbine_id=1))
    t2 = TurbineState(TurbineConfig(turbine_id=1))

    for _ in range(5):
        t1.tick(dt=1.0)
        t2.tick(dt=1.0)

    assert t1.wind_speed_mps == t2.wind_speed_mps
    assert t1.gearbox_temp_c == t2.gearbox_temp_c
