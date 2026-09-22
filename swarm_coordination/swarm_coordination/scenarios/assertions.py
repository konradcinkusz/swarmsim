"""Assertions over a trace: every number in a violation is measured, never declared.

Each assertion reads the recorded truth (where the drones really were, what their
autopilots were doing) and, for the mission, what the system under test *reported* —
and returns a headline measurement plus a violation for every breach, stamped with the
time it happened. Adding an assertion is a function here and a property in
contracts/scenario/scenario.v1.schema.json.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations

from ..mission_planning import FORMATIONS
from ..trajectory import Vector3
from .model import AssertionOutcome, Frame, Trace, Violation
from .spec import AssertionSpec, ScenarioSpec


def _vector(values) -> Vector3:
    return Vector3(float(values[0]), float(values[1]), float(values[2]))


def _window(trace: Trace, params: dict) -> list[Frame]:
    start = float(params.get("from_s", 0.0))
    end = float(params.get("to_s", float("inf")))
    return [f for f in trace.frames if start <= f.t_s <= end]


def _sample(frame: Frame, drone_id: str):
    return next(s for s in frame.drones if s.drone_id == drone_id)


def _outcome(kind: str, measured, unit: str, violations: list[Violation]) -> AssertionOutcome:
    return AssertionOutcome(kind, not violations, measured, unit, tuple(violations))


def min_separation(spec: ScenarioSpec, trace: Trace, params: dict) -> AssertionOutcome:
    limit = float(params["min_m"])
    closest: dict[tuple[str, str], tuple[float, float]] = {}
    for frame in _window(trace, params):
        airborne = [s for s in frame.drones if s.airborne]
        for a, b in combinations(airborne, 2):
            distance = a.position.distance_to(b.position)
            key = (a.drone_id, b.drone_id)
            if key not in closest or distance < closest[key][0]:
                closest[key] = (distance, frame.t_s)
    measured = min((d for d, _ in closest.values()), default=None)
    violations = [
        Violation(
            "min_separation",
            pair,
            t,
            round(d, 3),
            limit,
            f"{pair[0]} and {pair[1]} came within {d:.2f} m of each other at t={t:.1f} s "
            f"(minimum {limit:g} m)",
        )
        for pair, (d, t) in sorted(closest.items(), key=lambda item: item[1][1])
        if d < limit
    ]
    return _outcome(
        "min_separation", None if measured is None else round(measured, 3), "m", violations
    )


def mission_completes(spec: ScenarioSpec, trace: Trace, params: dict) -> AssertionOutcome:
    within = float(params["within_s"])
    if not trace.missions:
        violation = Violation(
            "mission_completes", (), None, None, within, "the scenario dispatched no mission"
        )
        return _outcome("mission_completes", None, "s", [violation])
    dispatched_at, mission_id, _ = trace.missions[-1]
    completed_at = next(
        (
            f.t_s
            for f in trace.frames
            if f.reported_mission_id == mission_id and f.reported_complete
        ),
        None,
    )
    if completed_at is None:
        description = f"mission {mission_id} was never reported complete"
        violation = Violation("mission_completes", (), None, None, within, description)
        return _outcome("mission_completes", None, "s", [violation])
    took = round(completed_at - dispatched_at, 3)
    violations = []
    if took > within:
        violations.append(
            Violation(
                "mission_completes",
                (),
                completed_at,
                took,
                within,
                f"mission {mission_id} reported complete after {took:.1f} s (limit {within:g} s)",
            )
        )
    return _outcome("mission_completes", took, "s", violations)


def all_landed(spec: ScenarioSpec, trace: Trace, params: dict) -> AssertionOutcome:
    by = float(params["by_s"])
    frames = [f for f in trace.frames if f.t_s <= by + 1e-9] or trace.frames[:1]
    last = frames[-1]
    flying = [s for s in last.drones if s.armed or s.airborne]
    if flying:
        violations = [
            Violation(
                "all_landed",
                (s.drone_id,),
                last.t_s,
                round(s.position.z, 3),
                0.0,
                f"{s.drone_id} still {'armed' if s.armed else 'airborne'} at t={last.t_s:.1f} s "
                f"(altitude {s.position.z:.2f} m, mode {s.mode})",
            )
            for s in flying
        ]
        return _outcome("all_landed", None, "s", violations)
    landed_since = last.t_s
    for frame in reversed(frames):
        if any(s.armed or s.airborne for s in frame.drones):
            break
        landed_since = frame.t_s
    return _outcome("all_landed", landed_since, "s", [])


def no_task_below_battery(spec: ScenarioSpec, trace: Trace, params: dict) -> AssertionOutcome:
    threshold = float(params["threshold_pct"])
    grace = float(params.get("grace_s", 3.0))
    longest = 0.0
    violations = []
    for drone_id in trace.homes:
        started = None
        reported = False
        for frame in trace.frames:
            sample = _sample(frame, drone_id)
            tasked_while_low = (
                sample.armed and sample.mode == "OFFBOARD" and (sample.battery_pct < threshold)
            )
            if not tasked_while_low:
                started, reported = None, False
                continue
            if started is None:
                started = frame.t_s
            held = frame.t_s - started
            longest = max(longest, held)
            if held > grace and not reported:
                reported = True
                violations.append(
                    Violation(
                        "no_task_below_battery",
                        (drone_id,),
                        frame.t_s,
                        round(sample.battery_pct, 2),
                        threshold,
                        f"{drone_id} still flying its task under the swarm's control "
                        f"{held:.1f} s after its battery fell below {threshold:g}% "
                        f"({sample.battery_pct:.1f}% at t={frame.t_s:.1f} s)",
                    )
                )
    return _outcome("no_task_below_battery", round(longest, 3), "s", violations)


def reaches(spec: ScenarioSpec, trace: Trace, params: dict) -> AssertionOutcome:
    drone_id = params["drone"]
    target = _vector(params["position"])
    tolerance = float(params["tolerance_m"])
    by = float(params["by_s"])
    start = float(params.get("from_s", 0.0))
    closest = None
    for frame in trace.frames:
        if frame.t_s > by + 1e-9:
            break
        if frame.t_s < start:
            continue
        distance = _sample(frame, drone_id).position.distance_to(target)
        closest = distance if closest is None else min(closest, distance)
        if distance <= tolerance:
            return _outcome("reaches", frame.t_s, "s", [])
    closest_text = "never measured" if closest is None else f"closest {closest:.2f} m"
    description = (
        f"{drone_id} never came within {tolerance:g} m of ({target.x:g}, {target.y:g}, "
        f"{target.z:g}) between t={start:g} s and t={by:g} s ({closest_text})"
    )
    violation = Violation(
        "reaches",
        (drone_id,),
        by,
        None if closest is None else round(closest, 3),
        tolerance,
        description,
    )
    return _outcome("reaches", None, "s", [violation])


def final_position(spec: ScenarioSpec, trace: Trace, params: dict) -> AssertionOutcome:
    drone_id = params["drone"]
    target = _vector(params["position"])
    tolerance = float(params["tolerance_m"])
    last = trace.frames[-1]
    position = _sample(last, drone_id).position
    distance = position.distance_to(target)
    violations = []
    if distance > tolerance:
        violations.append(
            Violation(
                "final_position",
                (drone_id,),
                last.t_s,
                round(distance, 3),
                tolerance,
                f"{drone_id} ended at ({position.x:.2f}, {position.y:.2f}, {position.z:.2f}), "
                f"{distance:.2f} m from ({target.x:g}, {target.y:g}, {target.z:g}) "
                f"(tolerance {tolerance:g} m)",
            )
        )
    return _outcome("final_position", round(distance, 3), "m", violations)


def formation_error(spec: ScenarioSpec, trace: Trace, params: dict) -> AssertionOutcome:
    limit = float(params["max_m"])
    formation_missions = [p for _, _, p in trace.missions if p["type"] == "formation"]
    if not formation_missions:
        violation = Violation(
            "formation_error", (), None, None, limit, "the scenario flew no formation mission"
        )
        return _outcome("formation_error", None, "m", [violation])
    mission = formation_missions[-1]
    ids = list(trace.homes)
    leader = params.get("leader", ids[0])
    start = ids.index(leader) + 1
    followers = ids[start : start + mission["drone_count"] - 1]
    offsets = FORMATIONS[mission["formation"]](len(followers), mission["spacing_m"])

    worst: dict[str, tuple[float, float]] = {}
    for frame in _window(trace, params):
        lead = _sample(frame, leader)
        if not lead.airborne or lead.mode != "OFFBOARD":
            continue
        for follower, offset in zip(followers, offsets, strict=True):
            sample = _sample(frame, follower)
            if not sample.airborne or sample.mode != "OFFBOARD":
                continue
            error = sample.position.distance_to(lead.position + offset)
            if follower not in worst or error > worst[follower][0]:
                worst[follower] = (error, frame.t_s)
    measured = max((e for e, _ in worst.values()), default=None)
    violations = [
        Violation(
            "formation_error",
            (follower, leader),
            t,
            round(error, 3),
            limit,
            f"{follower} was {error:.2f} m off its slot behind {leader} at t={t:.1f} s "
            f"(limit {limit:g} m)",
        )
        for follower, (error, t) in sorted(worst.items())
        if error > limit
    ]
    return _outcome(
        "formation_error", None if measured is None else round(measured, 3), "m", violations
    )


def never_mode(spec: ScenarioSpec, trace: Trace, params: dict) -> AssertionOutcome:
    drone_id = params["drone"]
    mode = params["mode"]
    for frame in trace.frames:
        if _sample(frame, drone_id).mode == mode:
            violation = Violation(
                "never_mode",
                (drone_id,),
                frame.t_s,
                None,
                None,
                f"{drone_id} entered {mode} at t={frame.t_s:.1f} s",
            )
            return _outcome("never_mode", frame.t_s, "s", [violation])
    return _outcome("never_mode", None, "s", [])


ASSERTIONS: dict[str, Callable[[ScenarioSpec, Trace, dict], AssertionOutcome]] = {
    "min_separation": min_separation,
    "mission_completes": mission_completes,
    "all_landed": all_landed,
    "no_task_below_battery": no_task_below_battery,
    "reaches": reaches,
    "final_position": final_position,
    "formation_error": formation_error,
    "never_mode": never_mode,
}


def evaluate(spec: ScenarioSpec, trace: Trace) -> tuple[AssertionOutcome, ...]:
    return tuple(ASSERTIONS[a.kind](spec, trace, a.params) for a in _checked(spec.assertions))


def _checked(assertions: tuple[AssertionSpec, ...]) -> tuple[AssertionSpec, ...]:
    unknown = [a.kind for a in assertions if a.kind not in ASSERTIONS]
    if unknown:
        raise ValueError(f"unknown assertion(s): {', '.join(unknown)}")
    return assertions
