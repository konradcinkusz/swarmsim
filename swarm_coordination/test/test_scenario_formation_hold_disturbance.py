import pytest

from swarm_coordination.scenarios import Scenario, Verdict
from swarm_coordination.scenarios.formation_hold_disturbance import SCENARIO, _run
from swarm_coordination.trajectory import Vector3

_MIN_SEPARATION_M = 1.0


def test_scenario_exposes_the_contract_fields():
    assert isinstance(SCENARIO, Scenario)
    assert SCENARIO.name == "formation_hold_disturbance"
    assert SCENARIO.description
    assert callable(SCENARIO.run)


def test_scenario_passes_under_its_bounded_default_disturbance():
    # SCENARIO.run() applies a fixed, representative GPS-jitter/wind-drift noise to
    # every follower; the ~2.8m nominal V-formation spacing should absorb it.
    verdict = SCENARIO.run()
    assert verdict == Verdict(passed=True, violations=[])


def test_no_violation_with_zero_disturbance():
    verdict = _run(noise_by_index={})
    assert verdict == Verdict(passed=True, violations=[])


def test_no_violation_under_bounded_noise_on_a_single_follower():
    # A light gust / GPS jitter on one follower, well inside the formation's margin.
    verdict = _run(noise_by_index={1: Vector3(0.3, 0.3, 0.0)})
    assert verdict.passed is True
    assert verdict.violations == []


def test_no_violation_under_bounded_noise_on_multiple_followers():
    verdict = _run(
        noise_by_index={
            1: Vector3(0.2, -0.2, 0.0),
            3: Vector3(-0.2, 0.2, 0.1),
        }
    )
    assert verdict.passed is True
    assert verdict.violations == []


def test_violation_detected_and_reported_when_noise_exceeds_the_formation_margin():
    # A large gust / GPS glitch drifts follower_1 across the formation, almost onto
    # the leader's position -- well beyond what the formation logic can absorb.
    verdict = _run(noise_by_index={1: Vector3(1.9, -1.9, 0.0)})

    assert verdict.passed is False
    assert len(verdict.violations) == 1

    violation = verdict.violations[0]
    assert violation.drone_ids == ["leader", "follower_1"]
    assert violation.timestamp_s == pytest.approx(12.5)
    assert violation.measured_value == pytest.approx(0.1414213562, abs=1e-6)
    assert violation.measured_value < violation.threshold
    assert violation.threshold == _MIN_SEPARATION_M
    assert "leader" in violation.description
    assert "follower_1" in violation.description


def test_violation_reports_a_custom_timestamp_and_threshold():
    verdict = _run(
        noise_by_index={2: Vector3(1.9, 1.9, 0.0)},
        min_separation_m=2.5,
        timestamp_s=42.0,
    )

    assert verdict.passed is False
    violation = verdict.violations[0]
    assert violation.timestamp_s == pytest.approx(42.0)
    assert violation.threshold == pytest.approx(2.5)
    assert violation.drone_ids == ["leader", "follower_2"]
