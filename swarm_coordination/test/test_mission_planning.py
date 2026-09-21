import pytest

from swarm_coordination.mission_planning import plan_swarm_waypoints
from swarm_coordination.trajectory import Vector3

BASE = [Vector3(0.0, 0.0, 5.0), Vector3(10.0, 0.0, 5.0)]


def test_waypoint_mode_assigns_every_drone_its_own_lane():
    plan = plan_swarm_waypoints("waypoint", BASE, drone_count=3, spacing_m=2.0)

    assert set(plan.keys()) == {"drone_1", "drone_2", "drone_3"}
    assert plan["drone_1"] == BASE
    assert plan["drone_2"] == [Vector3(0.0, 2.0, 5.0), Vector3(10.0, 2.0, 5.0)]
    assert plan["drone_3"] == [Vector3(0.0, 4.0, 5.0), Vector3(10.0, 4.0, 5.0)]


def test_formation_mode_only_assigns_the_leader():
    plan = plan_swarm_waypoints("formation", BASE, drone_count=4, spacing_m=2.0)

    assert set(plan.keys()) == {"drone_1"}
    assert plan["drone_1"] == BASE


def test_rejects_unknown_mission_type():
    with pytest.raises(ValueError):
        plan_swarm_waypoints("orbit", BASE, drone_count=1, spacing_m=1.0)


def test_rejects_empty_waypoints():
    with pytest.raises(ValueError):
        plan_swarm_waypoints("waypoint", [], drone_count=1, spacing_m=1.0)


def test_rejects_non_positive_drone_count():
    with pytest.raises(ValueError):
        plan_swarm_waypoints("waypoint", BASE, drone_count=0, spacing_m=1.0)


def test_single_drone_waypoint_mode_has_no_lane_offset():
    plan = plan_swarm_waypoints("waypoint", BASE, drone_count=1, spacing_m=2.0)
    assert plan["drone_1"] == BASE
