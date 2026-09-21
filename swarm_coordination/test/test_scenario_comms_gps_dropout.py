import pytest

from swarm_coordination.scenarios import Scenario, Verdict
from swarm_coordination.scenarios.comms_gps_dropout import SCENARIO, _dropped_ids, _run

_MIN_SEPARATION_M = 1.0
_MAX_SAFE_DROPOUT_FRACTION = 0.3


def test_scenario_exposes_the_contract_fields():
    assert isinstance(SCENARIO, Scenario)
    assert SCENARIO.name == "comms_gps_dropout"
    assert SCENARIO.description
    assert callable(SCENARIO.run)


def test_scenario_passes_under_its_default_low_dropout():
    # SCENARIO.run() drops a representative low percentage of the swarm; per the
    # stated degrade policy the still-connected drones should keep formation spacing.
    verdict = SCENARIO.run()
    assert verdict == Verdict(passed=True, violations=[])


def test_no_violation_with_zero_dropout():
    verdict = _run(dropout_fraction=0.0)
    assert verdict == Verdict(passed=True, violations=[])


def test_no_violation_under_a_low_dropout_among_connected_drones():
    # 20% dropout (the leader, deterministically) is well under the 30% max-safe
    # threshold, and the remaining followers keep their commanded spacing untouched.
    verdict = _run(dropout_fraction=0.2)
    assert verdict.passed is True
    assert verdict.violations == []


def test_violation_when_dropout_exceeds_the_max_safe_fraction():
    # 60% of the swarm loses comms/GPS -- well past the documented 30% maximum safe
    # dropout fraction -- so the dropout itself must be reported as a Violation, with
    # the concrete dropped drone ids, even though the two survivors are still spaced
    # apart under the "hold last commanded position" policy.
    verdict = _run(dropout_fraction=0.6)

    assert verdict.passed is False
    assert len(verdict.violations) == 1

    violation = verdict.violations[0]
    assert violation.drone_ids == ["leader", "follower_1", "follower_2"]
    assert violation.timestamp_s == pytest.approx(20.0)
    assert violation.measured_value == pytest.approx(0.6)
    assert violation.threshold == _MAX_SAFE_DROPOUT_FRACTION
    assert violation.measured_value > violation.threshold
    assert "60%" in violation.description
    assert "30%" in violation.description


def test_violation_reports_a_custom_threshold_and_timestamp():
    verdict = _run(
        dropout_fraction=0.5,
        max_safe_dropout_fraction=0.4,
        timestamp_s=99.0,
    )

    assert verdict.passed is False
    assert len(verdict.violations) == 1

    violation = verdict.violations[0]
    assert violation.drone_ids == ["leader", "follower_1"]
    assert violation.timestamp_s == pytest.approx(99.0)
    assert violation.measured_value == pytest.approx(0.5)
    assert violation.threshold == pytest.approx(0.4)


def test_spacing_invariant_is_checked_only_among_still_connected_drones():
    # Drop only the leader (20%, under the max-safe fraction) but raise the spacing
    # threshold above the followers' natural spacing, so the spacing check -- not the
    # dropout-fraction check -- is what fires. This also proves the dropped leader is
    # excluded from the spacing check entirely, per the stated degrade policy.
    verdict = _run(dropout_fraction=0.2, min_separation_m=3.0)

    assert verdict.passed is False
    assert len(verdict.violations) == 1

    violation = verdict.violations[0]
    assert "leader" not in violation.drone_ids
    assert violation.drone_ids == ["follower_1", "follower_3"]
    assert violation.measured_value == pytest.approx(2.8284271247, abs=1e-6)
    assert violation.threshold == pytest.approx(3.0)
    assert "still-connected" in violation.description


def test_dropped_ids_rejects_an_out_of_range_fraction():
    with pytest.raises(ValueError):
        _dropped_ids(1.5, ["a", "b"])
    with pytest.raises(ValueError):
        _dropped_ids(-0.1, ["a", "b"])
