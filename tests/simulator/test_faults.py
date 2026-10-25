import pytest

from windfarm.common.status import FaultType
from windfarm.simulator.faults import ActiveFault, fault_type_from_name


@pytest.mark.parametrize(
    "name,expected",
    [
        ("overspeed", FaultType.OVERSPEED),
        ("OVERSPEED", FaultType.OVERSPEED),
        ("  overheating  ", FaultType.OVERHEATING),
        ("comm_loss", FaultType.COMM_LOSS),
    ],
)
def test_fault_type_from_name_accepts_case_and_whitespace(name, expected):
    assert fault_type_from_name(name) is expected


def test_fault_type_from_name_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown fault type"):
        fault_type_from_name("warp_core_breach")


def test_active_fault_expiry():
    fault = ActiveFault(fault_type=FaultType.OVERSPEED, started_at=0.0, expires_at=10.0)
    assert fault.is_expired(9.9) is False
    assert fault.is_expired(10.0) is True


def test_active_fault_without_expiry_never_expires():
    fault = ActiveFault(fault_type=FaultType.COMM_LOSS, started_at=0.0, expires_at=None)
    assert fault.is_expired(1_000_000.0) is False
