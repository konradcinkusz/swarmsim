"""fit_formation finds the closest fit of drones to a formation, checked against brute force."""

import itertools
import random

import pytest

from swarm_coordination.formation import line_formation, v_formation
from swarm_coordination.scenarios.fit import bottleneck_assignment, fit_formation
from swarm_coordination.trajectory import Vector3


def _brute_force_bottleneck(cost):
    return min(
        max(cost[row][column] for row, column in enumerate(columns))
        for columns in itertools.permutations(range(len(cost)))
    )


def test_bottleneck_assignment_is_the_smallest_largest_cost_of_random_matrices():
    rng = random.Random(11)
    for _ in range(300):
        size = rng.randint(1, 6)
        cost = [[rng.uniform(0, 20) for _ in range(size)] for _ in range(size)]
        error, assignment = bottleneck_assignment(cost)
        assert sorted(assignment) == list(range(size))
        assert max(cost[row][column] for row, column in enumerate(assignment)) == error
        assert error == pytest.approx(_brute_force_bottleneck(cost))


def test_the_bottleneck_is_not_the_cheapest_total():
    """Matching (0,0) and (1,1) is cheapest in total (5 against 8), and its largest cost is 5.
    The other matching costs 4 and 4. A formation passes max_m if *every* drone is within
    it, so the bottleneck is the right fit."""
    error, assignment = bottleneck_assignment([[0.0, 4.0], [4.0, 5.0]])

    assert error == 4.0 and assignment == [1, 0]


def test_a_square_matrix_is_required_and_nothing_to_match_costs_nothing():
    assert bottleneck_assignment([]) == (0.0, [])
    with pytest.raises(ValueError):
        bottleneck_assignment([[1.0, 2.0]])


def _positions(*points):
    return {f"drone_{n}": Vector3(*p) for n, p in enumerate(points, start=1)}


def test_fit_formation_equals_brute_force_over_every_leader_and_every_order():
    rng = random.Random(5)
    for formation in (line_formation, v_formation):
        for count in (2, 3, 4, 5):
            offsets = formation(count - 1, 3.0)
            for _ in range(20):
                positions = _positions(
                    *[(rng.uniform(0, 12), rng.uniform(0, 12), 5.0) for _ in range(count)]
                )
                expected = min(
                    max(
                        positions[d].distance_to(positions[apex] + offsets[slot])
                        for d, slot in zip([d for d in positions if d != apex], order, strict=True)
                    )
                    for apex in positions
                    for order in itertools.permutations(range(count - 1))
                )

                fit = fit_formation(positions, offsets)

                assert fit.error_m == pytest.approx(expected)
                assert max(fit.errors.values()) == fit.error_m
                assert sorted(fit.slots.values()) == list(range(count - 1))


def test_the_drone_in_the_middle_of_a_line_can_lead_it():
    positions = _positions((6, 0, 5), (10, 0, 5), (8, 0, 5))  # 1 is last, 2 leads, 3 is between

    fit = fit_formation(positions, line_formation(2, 2.0))

    assert fit.leader == "drone_2" and fit.error_m == 0.0
    assert fit.slots == {"drone_1": 1, "drone_3": 0}  # the slots 2 m and 4 m behind


def test_a_pinned_leader_is_the_apex_and_a_tie_goes_to_the_first_drone():
    positions = _positions((0, 0, 5), (0, 3, 5))  # a line of two: either can lead, at 3 m
    offsets = [Vector3(0.0, 3.0, 0.0)]  # one slot, 3 m to the side

    assert fit_formation(positions, offsets).leader == "drone_1"
    assert fit_formation(positions, offsets, leader="drone_2").leader == "drone_2"
    assert fit_formation(positions, offsets, leader="drone_2").error_m == 6.0


def test_a_lone_leader_has_nothing_to_fit_and_a_wrong_count_is_refused():
    assert fit_formation(_positions((0, 0, 5)), []).error_m == 0.0
    with pytest.raises(ValueError, match="drone"):
        fit_formation(_positions((0, 0, 5), (1, 0, 5)), line_formation(2, 3.0))
    with pytest.raises(ValueError, match="drone_9"):
        fit_formation(_positions((0, 0, 5), (1, 0, 5)), line_formation(1, 3.0), leader="drone_9")
