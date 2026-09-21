import pytest

from swarm_coordination.scenarios.jamming_resilience import (
    _COMMS_TIMEOUT_S,
    _HOME,
    _POSITION_TOLERANCE_M,
    _TICK_S,
    SCENARIO,
    _check_reached_target,
    _leader_track,
    _simulate_follower,
)
from swarm_coordination.trajectory import Vector3

# The V-formation follower with the largest offset from the leader (rank 2, index 3 of
# v_formation(4, spacing_m=2.0)) --- the slowest one to reach home under RTH, so it is
# the sharpest edge case for both the "reaches fallback in time" and "not yet" checks.
_FAR_OFFSET = Vector3(-4.0, -4.0, 0.0)


def test_scenario_metadata_matches_contract():
    assert SCENARIO.name == "jamming_resilience"
    assert callable(SCENARIO.run)


def test_scenario_passes_end_to_end():
    verdict = SCENARIO.run()
    assert verdict.passed is True
    assert verdict.violations == []


def test_short_jamming_holds_position_while_comms_are_down():
    leader_track = _leader_track(ticks=20)
    positions = _simulate_follower(
        leader_track, _FAR_OFFSET, jam_start_tick=0, jam_duration_ticks=3
    )
    initial = leader_track[0] + _FAR_OFFSET
    # For the whole jammed window the follower must sit exactly where it was last
    # commanded -- not drift, not dead-reckon toward a target it can no longer hear.
    assert positions[0] == initial
    assert positions[1] == initial
    assert positions[2] == initial


def test_short_jamming_recovers_into_formation_once_comms_return():
    leader_track = _leader_track(ticks=20)
    positions = _simulate_follower(
        leader_track, _FAR_OFFSET, jam_start_tick=0, jam_duration_ticks=3
    )
    expected_final = leader_track[-1] + _FAR_OFFSET
    assert positions[-1].distance_to(expected_final) == pytest.approx(0.0, abs=1e-9)


def test_sustained_jamming_triggers_return_to_home():
    leader_track = _leader_track(ticks=20)
    positions = _simulate_follower(
        leader_track, _FAR_OFFSET, jam_start_tick=0, jam_duration_ticks=20
    )
    assert positions[-1].distance_to(_HOME) == pytest.approx(0.0, abs=1e-9)


def test_check_reached_target_passes_within_tolerance():
    position = Vector3(_HOME.x + _POSITION_TOLERANCE_M / 2, _HOME.y, _HOME.z)
    violation = _check_reached_target(
        "follower-0", position, _HOME, timestamp_s=10.0, description="within tolerance"
    )
    assert violation is None


def test_check_reached_target_reports_violation_with_concrete_details():
    off_position = Vector3(_HOME.x + 50.0, _HOME.y, _HOME.z)
    violation = _check_reached_target(
        "follower-2",
        off_position,
        _HOME,
        timestamp_s=12.0,
        description="follower parked outside the documented fallback position",
    )
    assert violation is not None
    assert violation.drone_ids == ["follower-2"]
    assert violation.timestamp_s == 12.0
    assert violation.measured_value == pytest.approx(50.0)
    assert violation.threshold == _POSITION_TOLERANCE_M
    assert violation.description == "follower parked outside the documented fallback position"


def test_insufficient_time_after_sustained_jamming_is_a_violation():
    # Real hold/RTH pipeline, but the run stops just 1 tick after the fallback
    # triggers -- not enough time for the farthest follower to actually reach home.
    # The documented fallback state has not yet been reached, and the check must
    # flag that, not silently treat "still jammed" as compliant.
    jam_ticks = _COMMS_TIMEOUT_S / _TICK_S + 1
    leader_track = _leader_track(ticks=int(jam_ticks))
    positions = _simulate_follower(
        leader_track, _FAR_OFFSET, jam_start_tick=0, jam_duration_ticks=int(jam_ticks)
    )
    timestamp_s = (len(positions) - 1) * _TICK_S
    violation = _check_reached_target(
        "follower-3",
        positions[-1],
        _HOME,
        timestamp_s,
        "follower did not reach the documented RTH fallback position after sustained "
        "jamming",
    )
    assert violation is not None
    assert violation.drone_ids == ["follower-3"]
    assert violation.timestamp_s == timestamp_s
    assert violation.measured_value > _POSITION_TOLERANCE_M
    assert violation.threshold == _POSITION_TOLERANCE_M
