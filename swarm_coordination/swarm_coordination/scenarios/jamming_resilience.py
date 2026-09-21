"""Jamming resilience: sustained loss of inter-drone/ground comms mid-mission.

Explicit fallback policy under test (stated here, not left implicit): while comms are
jammed, a follower HOLDS its last known commanded position and mission state --- it
does not keep dead-reckoning toward a moving formation target it can no longer hear
updates for. If comms are restored before ``_COMMS_TIMEOUT_S`` seconds of continuous
jamming have elapsed, the follower resumes the mission: it re-acquires its live
formation target and flies to catch up. If jamming is instead still in effect once
``_COMMS_TIMEOUT_S`` elapses, the follower gives up on resuming and instead executes a
pre-programmed return-to-home (RTH): it flies back to ``_HOME`` and parks there.
Re-tasking a drone that has already gone RTH is out of scope for this scenario --- once
triggered, RTH is terminal for the run, so a swarm that is still sitting at home when
comms come back later is compliant, not a bug this scenario checks for.

This scenario checks both edges of that policy against a straight-line-flying leader
and its V-formation followers (see ``formation.py``):

* short jamming --- comms return well inside the timeout, so every follower must
  hold, then resume, then rejoin its live formation target;
* sustained jamming --- comms never return within the run, so every follower must
  reach the documented RTH fallback (parked at ``_HOME``) with time to spare.

A follower that ends up anywhere else at the point its policy state is checked --- for
example still short of home after the timeout, or short of its formation slot after a
brief outage --- is reported as a ``Violation`` giving the offending drone id, the
distance it missed its expected position by, and the allowed tolerance.
"""

from __future__ import annotations

from ..formation import v_formation
from ..trajectory import Vector3, step_towards
from . import Scenario, Verdict, Violation

# One simulated tick == one second, so tick counts and elapsed seconds coincide.
_TICK_S = 1.0

# How long comms must be continuously down before a follower gives up on resuming and
# falls back to return-to-home, per the documented policy above.
_COMMS_TIMEOUT_S = 5.0
_TIMEOUT_TICKS = int(_COMMS_TIMEOUT_S / _TICK_S)

# Max distance a follower can close per tick, and the leader's constant flight speed.
# Chosen so a follower closes ground on the leader faster than the leader opens it
# (required for "resume and rejoin" to ever actually converge after an outage).
_STEP_M = 2.0
_LEADER_SPEED_M_S = 1.0

_HOME = Vector3(0.0, 0.0, 5.0)
_FOLLOWER_COUNT = 4
_SPACING_M = 2.0

# How close a follower must end up to its expected policy position to count as
# compliant; this is slack for floating-point step accumulation, not a safety margin.
_POSITION_TOLERANCE_M = 0.05

_FOLLOWER_IDS = [f"follower-{i}" for i in range(_FOLLOWER_COUNT)]

# Ticks simulated for each sub-check; generous relative to the distances involved (see
# module docstring) so "not yet converged" never masquerades as a policy violation.
_SHORT_JAM_TICKS = 3
_SHORT_JAM_RUN_TICKS = 20
_SUSTAINED_JAM_RUN_TICKS = 20


def _leader_track(ticks: int) -> list[Vector3]:
    """The leader's ground-truth trajectory: constant-velocity flight along +x."""
    return [
        Vector3(_HOME.x + _LEADER_SPEED_M_S * _TICK_S * t, _HOME.y, _HOME.z) for t in range(ticks)
    ]


def _simulate_follower(
    leader_positions: list[Vector3],
    offset: Vector3,
    jam_start_tick: int,
    jam_duration_ticks: int,
) -> list[Vector3]:
    """One follower's position at every tick under the documented fallback policy.

    ``leader_positions`` is the leader's ground truth at each tick (what the follower
    would track if comms were up). Comms are jammed for ``jam_duration_ticks`` ticks
    starting at ``jam_start_tick``; outside that window the follower tracks the leader
    normally. See the module docstring for the hold/resume/RTH policy this implements.
    """
    position = leader_positions[0] + offset
    held_target = position
    rth_triggered = False
    jammed_ticks = 0
    positions: list[Vector3] = []
    for t, leader_pos in enumerate(leader_positions):
        jammed = jam_start_tick <= t < jam_start_tick + jam_duration_ticks
        if jammed:
            jammed_ticks += 1
            if jammed_ticks * _TICK_S >= _COMMS_TIMEOUT_S:
                rth_triggered = True
            target = _HOME if rth_triggered else held_target
        else:
            jammed_ticks = 0
            if rth_triggered:
                target = _HOME
            else:
                held_target = leader_pos + offset
                target = held_target
        position = step_towards(position, target, _STEP_M)
        positions.append(position)
    return positions


def _check_reached_target(
    drone_id: str,
    position: Vector3,
    expected: Vector3,
    timestamp_s: float,
    description: str,
) -> Violation | None:
    """None if ``position`` is within ``_POSITION_TOLERANCE_M`` of ``expected``."""
    distance = position.distance_to(expected)
    if distance > _POSITION_TOLERANCE_M:
        return Violation(
            drone_ids=[drone_id],
            timestamp_s=timestamp_s,
            measured_value=distance,
            threshold=_POSITION_TOLERANCE_M,
            description=description,
        )
    return None


def _run() -> Verdict:
    """Check the hold/resume/RTH fallback policy under short and sustained jamming."""
    violations: list[Violation] = []
    offsets = v_formation(count=_FOLLOWER_COUNT, spacing_m=_SPACING_M)

    # Sustained jamming: comms never return within the run, so every follower must
    # have reached the documented RTH fallback (parked at home) by the end of it.
    sustained_leader_track = _leader_track(ticks=_SUSTAINED_JAM_RUN_TICKS)
    for drone_id, offset in zip(_FOLLOWER_IDS, offsets, strict=True):
        positions = _simulate_follower(
            sustained_leader_track,
            offset,
            jam_start_tick=0,
            jam_duration_ticks=_SUSTAINED_JAM_RUN_TICKS,
        )
        timestamp_s = (len(positions) - 1) * _TICK_S
        violation = _check_reached_target(
            drone_id,
            positions[-1],
            _HOME,
            timestamp_s,
            "follower did not reach the documented RTH fallback position after "
            "sustained jamming",
        )
        if violation is not None:
            violations.append(violation)

    # Short jamming: comms return well before the timeout, so every follower must
    # have held, then resumed the mission and rejoined its live formation target.
    short_leader_track = _leader_track(ticks=_SHORT_JAM_RUN_TICKS)
    for drone_id, offset in zip(_FOLLOWER_IDS, offsets, strict=True):
        positions = _simulate_follower(
            short_leader_track,
            offset,
            jam_start_tick=0,
            jam_duration_ticks=_SHORT_JAM_TICKS,
        )
        timestamp_s = (len(positions) - 1) * _TICK_S
        expected_final = short_leader_track[-1] + offset
        violation = _check_reached_target(
            drone_id,
            positions[-1],
            expected_final,
            timestamp_s,
            "follower did not recover into formation after a short jamming event",
        )
        if violation is not None:
            violations.append(violation)

    if violations:
        return Verdict(passed=False, violations=violations)
    return Verdict(passed=True)


SCENARIO = Scenario(
    name="jamming_resilience",
    description=(
        "Loss of inter-drone/ground comms for a duration. Fallback policy: hold last "
        "known position and mission state until comms are restored or "
        f"{_COMMS_TIMEOUT_S:.0f}s elapse, then either resume the mission or execute a "
        "pre-programmed return-to-home. Checks both a short jamming event (recovers "
        "into formation) and sustained jamming (reaches the RTH fallback state)."
    ),
    run=_run,
)
