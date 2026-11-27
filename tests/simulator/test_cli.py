from windfarm.simulator.cli import build_turbine_states


def _run_ticks(turbine_count: int, seed: int | None, ticks: int = 5) -> list[tuple[float, float]]:
    states = build_turbine_states(turbine_count, seed)
    for _ in range(ticks):
        for state in states.values():
            state.tick(dt=1.0, now=0.0)
    return [(state.wind_speed_mps, state.gearbox_temp_c) for state in states.values()]


def test_omitting_seed_produces_different_telemetry_across_separate_runs():
    """The --seed flag is documented as giving reproducibility that wouldn't otherwise
    exist, implying that omitting it yields genuine run-to-run randomness. Two
    independent "runs" (separate calls to build_turbine_states, as the CLI does per
    process) without a seed must not produce bit-for-bit identical telemetry.
    """
    run1 = _run_ticks(turbine_count=1, seed=None)
    run2 = _run_ticks(turbine_count=1, seed=None)

    assert run1 != run2


def test_same_seed_still_reproduces_identical_telemetry():
    """Explicitly requested reproducibility via --seed must keep working."""
    run1 = _run_ticks(turbine_count=1, seed=42)
    run2 = _run_ticks(turbine_count=1, seed=42)

    assert run1 == run2
