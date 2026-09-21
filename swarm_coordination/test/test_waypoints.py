import pytest

from swarm_coordination.trajectory import Vector3
from swarm_coordination.waypoints import WaypointQueue


def _queue():
    return WaypointQueue(
        waypoints=[Vector3(0.0, 0.0, 5.0), Vector3(10.0, 0.0, 5.0), Vector3(10.0, 10.0, 5.0)],
        tolerance_m=0.5,
    )


def test_current_starts_at_first_waypoint():
    q = _queue()
    assert q.current == Vector3(0.0, 0.0, 5.0)
    assert not q.is_complete
    assert q.remaining == 3


def test_advance_only_fires_within_tolerance():
    q = _queue()
    far = Vector3(0.0, 0.0, 0.0)  # 5m away in z, outside 0.5m tolerance
    assert q.advance(far) is False
    assert q.current == Vector3(0.0, 0.0, 5.0)

    close = Vector3(0.1, 0.0, 5.0)
    assert q.advance(close) is True
    assert q.current == Vector3(10.0, 0.0, 5.0)


def test_queue_completes_after_last_waypoint():
    q = _queue()
    position = Vector3(0.0, 0.0, 5.0)
    for _ in range(len(q.waypoints)):
        q.advance(position)
        position = q.current or position
    assert q.is_complete
    assert q.current is None
    assert q.remaining == 0


def test_step_holds_position_once_complete():
    q = WaypointQueue(waypoints=[Vector3(1.0, 0.0, 0.0)], tolerance_m=0.5)
    q.advance(Vector3(1.0, 0.0, 0.0))
    assert q.is_complete
    held = q.step(Vector3(1.0, 0.0, 0.0), max_step=1.0)
    assert held == Vector3(1.0, 0.0, 0.0)


def test_step_moves_towards_current_waypoint():
    q = _queue()
    next_position = q.step(Vector3(0.0, 0.0, 0.0), max_step=1.0)
    # First waypoint is (0,0,5): straight up.
    assert next_position == Vector3(0.0, 0.0, 1.0)


def test_reaching_a_waypoint_mid_flight_retargets_next_step():
    q = WaypointQueue(
        waypoints=[Vector3(1.0, 0.0, 0.0), Vector3(1.0, 5.0, 0.0)], tolerance_m=0.5
    )
    # Already within tolerance of the first waypoint: step() should advance and then
    # aim at the second waypoint in the same call.
    result = q.step(Vector3(1.0, 0.1, 0.0), max_step=1.0)
    assert result == Vector3(1.0, 1.1, 0.0)


@pytest.mark.parametrize("tolerance", [0.0, 0.1, 5.0])
def test_various_tolerances_do_not_raise(tolerance):
    q = WaypointQueue(waypoints=[Vector3(0, 0, 0)], tolerance_m=tolerance)
    q.advance(Vector3(0, 0, 0))
