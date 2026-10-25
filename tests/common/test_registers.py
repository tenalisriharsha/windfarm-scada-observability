import pytest

from windfarm.common.registers import (
    REGISTER_COUNT,
    decode_reading,
    encode_reading,
)
from windfarm.common.status import TurbineStatus


def test_encode_produces_expected_register_count():
    registers = encode_reading(
        rotor_speed_rpm=15.3,
        power_output_kw=1234.5,
        wind_speed_mps=9.87,
        gearbox_temp_c=65.4,
        status_code=TurbineStatus.OK,
    )
    assert len(registers) == REGISTER_COUNT
    assert all(0 <= r <= 0xFFFF for r in registers)


def test_round_trip_preserves_values_within_scale_resolution():
    reading = decode_reading(
        encode_reading(
            rotor_speed_rpm=18.2,
            power_output_kw=2000.0,
            wind_speed_mps=12.34,
            gearbox_temp_c=72.1,
            status_code=TurbineStatus.WARNING,
        )
    )
    assert reading.rotor_speed_rpm == pytest.approx(18.2, abs=0.05)
    assert reading.power_output_kw == pytest.approx(2000.0, abs=0.05)
    assert reading.wind_speed_mps == pytest.approx(12.34, abs=0.005)
    assert reading.gearbox_temp_c == pytest.approx(72.1, abs=0.05)
    assert reading.status_code == TurbineStatus.WARNING


def test_round_trip_overspeed_fault_extremes_fit_in_register():
    registers = encode_reading(
        rotor_speed_rpm=29.0,
        power_output_kw=2600.0,
        wind_speed_mps=24.9,
        gearbox_temp_c=140.0,
        status_code=TurbineStatus.FAULT_OVERSPEED,
    )
    reading = decode_reading(registers)
    assert reading.status_code == TurbineStatus.FAULT_OVERSPEED
    assert reading.rotor_speed_rpm == pytest.approx(29.0, abs=0.05)
    assert reading.gearbox_temp_c == pytest.approx(140.0, abs=0.05)


def test_negative_values_clamp_to_zero_rather_than_wrapping():
    registers = encode_reading(
        rotor_speed_rpm=-5.0,
        power_output_kw=-1.0,
        wind_speed_mps=0.0,
        gearbox_temp_c=-10.0,
        status_code=TurbineStatus.OK,
    )
    reading = decode_reading(registers)
    assert reading.rotor_speed_rpm == 0.0
    assert reading.power_output_kw == 0.0
    assert reading.gearbox_temp_c == 0.0


def test_decode_rejects_wrong_register_count():
    with pytest.raises(ValueError):
        decode_reading([1, 2, 3])
