import math

import pytest

from swarm_coordination.trajectory import Vector3, step_towards


def test_vector_arithmetic():
    a = Vector3(1.0, 2.0, 3.0)
    b = Vector3(4.0, 0.0, -1.0)
    assert a + b == Vector3(5.0, 2.0, 2.0)
    assert a - b == Vector3(-3.0, 2.0, 4.0)
    assert a.scale(2.0) == Vector3(2.0, 4.0, 6.0)


def test_norm_and_distance():
    origin = Vector3(0.0, 0.0, 0.0)
    p = Vector3(3.0, 4.0, 0.0)
    assert p.norm() == pytest.approx(5.0)
    assert origin.distance_to(p) == pytest.approx(5.0)


def test_step_towards_reaches_target_exactly_within_max_step():
    current = Vector3(0.0, 0.0, 0.0)
    target = Vector3(0.3, 0.0, 0.0)
    result = step_towards(current, target, max_step=0.5)
    assert result == target


def test_step_towards_moves_partway_when_farther_than_max_step():
    current = Vector3(0.0, 0.0, 0.0)
    target = Vector3(10.0, 0.0, 0.0)
    result = step_towards(current, target, max_step=1.0)
    assert result.distance_to(current) == pytest.approx(1.0)
    assert result.distance_to(target) == pytest.approx(9.0)


def test_step_towards_converges_in_finite_steps():
    current = Vector3(0.0, 0.0, 0.0)
    target = Vector3(5.0, 5.0, 0.0)
    max_step = 0.7
    steps = 0
    while current != target:
        current = step_towards(current, target, max_step)
        steps += 1
        assert steps < 1000, "did not converge"
    assert current == target
    assert steps == math.ceil(target.norm() / max_step)


def test_step_towards_rejects_non_positive_step():
    with pytest.raises(ValueError):
        step_towards(Vector3(0, 0, 0), Vector3(1, 0, 0), max_step=0)
