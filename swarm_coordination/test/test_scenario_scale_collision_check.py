import pytest

from swarm_coordination.scenarios import Scenario, Verdict
from swarm_coordination.scenarios.scale_collision_check import (
    _LARGE_FOLLOWER_COUNT,
    _MIN_EXPECTED_GROWTH_RATIO,
    _MIN_SEPARATION_M,
    _SMALL_FOLLOWER_COUNT,
    SCENARIO,
    _check_scale,
    _growth_violation,
    _pairwise_comparison_count,
    _run,
)

_SMALL_SEPARATION_M = pytest.approx(2.8284271247, abs=1e-6)  # sqrt(2**2 + 2**2)


def test_scenario_exposes_the_contract_fields():
    assert isinstance(SCENARIO, Scenario)
    assert SCENARIO.name == "scale_collision_check"
    assert SCENARIO.description
    assert callable(SCENARIO.run)


def test_scenario_passes_at_its_default_scales():
    # Both the small and large default formations are held with zero perturbation and
    # a real separation threshold, so neither should report a collision, and the
    # default counts are chosen to show clearly super-linear comparison growth.
    verdict = SCENARIO.run()
    assert verdict == Verdict(passed=True, violations=[])


# --- Correctness at both scales (has_collision/min_separation give right answers) ---


def test_no_collision_at_small_scale():
    assert _check_scale(_SMALL_FOLLOWER_COUNT, _MIN_SEPARATION_M, timestamp_s=0.0) is None


def test_no_collision_at_large_scale():
    assert _check_scale(_LARGE_FOLLOWER_COUNT, _MIN_SEPARATION_M, timestamp_s=0.0) is None


def test_violation_detected_and_reported_when_threshold_exceeds_actual_spacing():
    # A threshold (5.0m) well above the ~2.83m leader-to-nearest-follower spacing the
    # 5-follower V formation actually has forces has_collision/min_separation to
    # report a breach, exercising the failing path with concrete, checkable details.
    violation = _check_scale(_SMALL_FOLLOWER_COUNT, min_separation_m=5.0, timestamp_s=7.5)

    assert violation is not None
    assert violation.drone_ids == ["leader", "follower_1"]
    assert violation.timestamp_s == pytest.approx(7.5)
    assert violation.measured_value == _SMALL_SEPARATION_M
    assert violation.measured_value < violation.threshold
    assert violation.threshold == pytest.approx(5.0)
    assert "leader" in violation.description
    assert "follower_1" in violation.description


def test_violation_detected_at_large_scale_too():
    violation = _check_scale(_LARGE_FOLLOWER_COUNT, min_separation_m=5.0, timestamp_s=3.0)

    assert violation is not None
    assert violation.drone_ids == ["leader", "follower_1"]
    assert violation.measured_value == _SMALL_SEPARATION_M
    assert violation.threshold == pytest.approx(5.0)


def test_run_reports_a_violation_per_scale_when_threshold_is_too_tight():
    verdict = _run(min_separation_m=5.0, timestamp_s=1.0)

    assert verdict.passed is False
    # One violation per scale that failed, plus none from the (unaffected) growth
    # check, since the two default counts still grow comparisons quadratically.
    assert len(verdict.violations) == 2
    assert {tuple(v.drone_ids) for v in verdict.violations} == {("leader", "follower_1")}


# --- Deterministic assertion on comparison-count growth (not wall-clock timing) ---


def test_pairwise_comparison_count_is_n_choose_2():
    assert _pairwise_comparison_count(0) == 0
    assert _pairwise_comparison_count(1) == 0
    assert _pairwise_comparison_count(2) == 1
    assert _pairwise_comparison_count(6) == 15
    assert _pairwise_comparison_count(26) == 325


def test_comparison_count_grows_quadratically_between_default_scales():
    small_comparisons = _pairwise_comparison_count(_SMALL_FOLLOWER_COUNT + 1)
    large_comparisons = _pairwise_comparison_count(_LARGE_FOLLOWER_COUNT + 1)
    drone_count_ratio = (_LARGE_FOLLOWER_COUNT + 1) / (_SMALL_FOLLOWER_COUNT + 1)

    assert small_comparisons == 15
    assert large_comparisons == 325
    growth_ratio = large_comparisons / small_comparisons
    # A linear check's cost would grow by drone_count_ratio (~4.3x); the actual,
    # deterministic growth is far larger, showing ~n^2 rather than ~n scaling.
    assert growth_ratio > drone_count_ratio * 3
    assert growth_ratio >= _MIN_EXPECTED_GROWTH_RATIO


def test_growth_violation_is_none_for_the_default_scales():
    assert _growth_violation(_SMALL_FOLLOWER_COUNT, _LARGE_FOLLOWER_COUNT, timestamp_s=0.0) is None


def test_growth_violation_detected_and_reported_when_counts_do_not_grow():
    # Equal follower counts give a comparison-growth ratio of exactly 1.0 --- no
    # growth at all --- which must be caught as a violation.
    violation = _growth_violation(_SMALL_FOLLOWER_COUNT, _SMALL_FOLLOWER_COUNT, timestamp_s=4.0)

    assert violation is not None
    assert violation.drone_ids == []
    assert violation.timestamp_s == pytest.approx(4.0)
    assert violation.measured_value == pytest.approx(1.0)
    assert violation.threshold == pytest.approx(_MIN_EXPECTED_GROWTH_RATIO)
    assert violation.measured_value < violation.threshold
    assert "short of" in violation.description
    assert str(_SMALL_FOLLOWER_COUNT) in violation.description
