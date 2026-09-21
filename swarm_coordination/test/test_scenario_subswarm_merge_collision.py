import pytest

from swarm_coordination.scenarios import Scenario, Verdict
from swarm_coordination.scenarios.subswarm_merge_collision import (
    SCENARIO,
    _check_merge,
    _SubSwarm,
)
from swarm_coordination.trajectory import Vector3


def test_scenario_exposes_the_contract_fields():
    assert isinstance(SCENARIO, Scenario)
    assert SCENARIO.name == "subswarm_merge_no_collision"
    assert SCENARIO.description
    assert callable(SCENARIO.run)


def test_safe_merge_produces_no_violations():
    # SCENARIO's two sub-swarms cross ground tracks 3m apart in altitude, which keeps
    # every pair at least 3m apart even at the moment their tracks cross.
    verdict = SCENARIO.run()
    assert verdict == Verdict(passed=True, violations=[])


def test_safe_merge_is_deterministic_across_runs():
    assert SCENARIO.run() == SCENARIO.run()


def test_crossing_subswarms_at_the_same_altitude_detect_a_collision():
    # Two single-drone sub-swarms, same altitude, crossing paths through the origin at
    # the same normalized time (t=0.5) -> they occupy the same point and collide.
    sub_swarm_a = _SubSwarm(
        drone_ids=["a1"],
        start=Vector3(-5.0, 0.0, 5.0),
        end=Vector3(5.0, 0.0, 5.0),
        offsets=[],
    )
    sub_swarm_b = _SubSwarm(
        drone_ids=["b1"],
        start=Vector3(0.0, -5.0, 5.0),
        end=Vector3(0.0, 5.0, 5.0),
        offsets=[],
    )

    verdict = _check_merge([sub_swarm_a, sub_swarm_b], min_separation_m=2.0, sample_count=5)

    assert verdict.passed is False
    assert len(verdict.violations) == 1

    violation = verdict.violations[0]
    assert violation.drone_ids == ["a1", "b1"]
    assert violation.timestamp_s == pytest.approx(5.0)
    assert violation.measured_value == pytest.approx(0.0, abs=1e-9)
    assert violation.threshold == 2.0
    assert "a1" in violation.description and "b1" in violation.description


def test_crossing_subswarms_far_from_the_merge_point_stay_clear():
    # Same crossing geometry, but sampled away from the t=0.5 crossing instant only ->
    # no violation, confirming the checker doesn't false-positive off-crossing.
    sub_swarm_a = _SubSwarm(
        drone_ids=["a1"],
        start=Vector3(-5.0, 0.0, 5.0),
        end=Vector3(5.0, 0.0, 5.0),
        offsets=[],
    )
    sub_swarm_b = _SubSwarm(
        drone_ids=["b1"],
        start=Vector3(0.0, -5.0, 5.0),
        end=Vector3(0.0, 5.0, 5.0),
        offsets=[],
    )

    # Two samples only: the start (t=0) and end (t=1) of the merge, both far apart.
    verdict = _check_merge([sub_swarm_a, sub_swarm_b], min_separation_m=2.0, sample_count=2)

    assert verdict == Verdict(passed=True, violations=[])


def test_subswarm_positions_at_include_leader_and_offset_followers():
    sub_swarm = _SubSwarm(
        drone_ids=["leader", "follower"],
        start=Vector3(0.0, 0.0, 5.0),
        end=Vector3(10.0, 0.0, 5.0),
        offsets=[Vector3(-3.0, 0.0, 0.0)],
    )
    positions = sub_swarm.positions_at(0.5)
    assert positions == [Vector3(5.0, 0.0, 5.0), Vector3(2.0, 0.0, 5.0)]
