import pytest

from swarm_coordination.formation import (
    follower_targets,
    has_collision,
    line_formation,
    min_separation,
    v_formation,
)
from swarm_coordination.trajectory import Vector3


def test_line_formation_offsets_are_spaced_behind_leader():
    offsets = line_formation(3, spacing_m=2.0)
    assert offsets == [Vector3(-2.0, 0, 0), Vector3(-4.0, 0, 0), Vector3(-6.0, 0, 0)]


def test_line_formation_zero_count():
    assert line_formation(0) == []


def test_line_formation_rejects_negative_count():
    with pytest.raises(ValueError):
        line_formation(-1)


def test_v_formation_alternates_sides():
    offsets = v_formation(4, spacing_m=2.0)
    assert offsets == [
        Vector3(-2.0, 2.0, 0),
        Vector3(-2.0, -2.0, 0),
        Vector3(-4.0, 4.0, 0),
        Vector3(-4.0, -4.0, 0),
    ]


def test_follower_targets_are_absolute_positions():
    leader = Vector3(10.0, 10.0, 5.0)
    offsets = line_formation(2, spacing_m=1.0)
    targets = follower_targets(leader, offsets)
    assert targets == [Vector3(9.0, 10.0, 5.0), Vector3(8.0, 10.0, 5.0)]


def test_min_separation_none_for_fewer_than_two():
    assert min_separation([]) is None
    assert min_separation([Vector3(0, 0, 0)]) is None


def test_min_separation_finds_closest_pair():
    positions = [Vector3(0, 0, 0), Vector3(10, 0, 0), Vector3(0, 1, 0)]
    assert min_separation(positions) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "min_distance_m,expected",
    [(0.5, False), (1.5, True)],
)
def test_has_collision_against_a_three_drone_line_formation(min_distance_m, expected):
    # Exercises "no collisions across at least 3 different starting-point sets" (M2).
    leader = Vector3(0.0, 0.0, 5.0)
    offsets = line_formation(2, spacing_m=1.0)
    positions = [leader] + follower_targets(leader, offsets)
    assert has_collision(positions, min_distance_m) is expected


def test_no_collision_across_three_formation_starting_points():
    for start in [Vector3(0, 0, 5), Vector3(100, -50, 20), Vector3(-30, 30, 5)]:
        offsets = v_formation(4, spacing_m=2.0)
        positions = [start] + follower_targets(start, offsets)
        assert has_collision(positions, min_distance_m=1.0) is False
