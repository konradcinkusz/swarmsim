"""Scenario: reallocate a low-battery drone's task rather than dropping it.

A drone's simulated battery drops below a configured threshold mid-mission. The
fleet's task assignments should be re-planned so an available drone (idle, and itself
still above the threshold) takes over the low-battery drone's task/waypoints instead
of it being silently dropped. If no replacement is available and the low-battery
drone is left still holding its task, that is reported as a ``Violation`` --- flying a
task on a depleted battery is itself the fault being caught here, not just a missed
handoff.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial

from . import Scenario, Verdict, Violation

_BATTERY_THRESHOLD_PCT = 20.0
_REALLOCATION_TIMESTAMP_S = 30.0


@dataclass(frozen=True)
class _Drone:
    """A drone's state at one instant: id, battery level, and its current task, if any."""

    drone_id: str
    battery_pct: float
    task_id: str | None


# The default fleet SCENARIO.run() exercises: drone_1 has dropped below threshold
# mid-mission while drone_3 sits idle and above threshold, so reallocation should
# succeed and the scenario should pass.
_DEFAULT_FLEET: list[_Drone] = [
    _Drone(drone_id="drone_1", battery_pct=15.0, task_id="waypoint_survey_a"),
    _Drone(drone_id="drone_2", battery_pct=90.0, task_id="waypoint_survey_b"),
    _Drone(drone_id="drone_3", battery_pct=95.0, task_id=None),
]


def reallocate_low_battery_tasks(
    drones: list[_Drone], threshold_pct: float = _BATTERY_THRESHOLD_PCT
) -> list[_Drone]:
    """Hand each below-threshold, tasked drone's task to an idle, above-threshold drone.

    A replacement candidate must be idle (``task_id is None``) and itself at or above
    ``threshold_pct`` --- a low-battery drone is never used to replace another. Both
    the drones needing a handoff and the available replacements are matched in
    ascending ``drone_id`` order, so the result is deterministic. A below-threshold
    drone with no available replacement keeps its task unchanged; ``_run`` turns that
    into a reported ``Violation``.
    """
    needs_replacement = [
        drone for drone in drones if drone.battery_pct < threshold_pct and drone.task_id is not None
    ]
    if not needs_replacement:
        return list(drones)

    by_id = {drone.drone_id: drone for drone in drones}
    available_ids = sorted(
        drone.drone_id
        for drone in drones
        if drone.battery_pct >= threshold_pct and drone.task_id is None
    )
    for low in sorted(needs_replacement, key=lambda drone: drone.drone_id):
        if not available_ids:
            continue
        replacement_id = available_ids.pop(0)
        by_id[replacement_id] = replace(by_id[replacement_id], task_id=low.task_id)
        by_id[low.drone_id] = replace(low, task_id=None)
    return [by_id[drone.drone_id] for drone in drones]


def _run(
    drones: list[_Drone],
    threshold_pct: float = _BATTERY_THRESHOLD_PCT,
    timestamp_s: float = _REALLOCATION_TIMESTAMP_S,
) -> Verdict:
    """Reallocate low-battery drones' tasks, then flag any still stuck below threshold.

    A drone that is still below ``threshold_pct`` and still holds a task after
    reallocation means no replacement was available for it --- it would otherwise keep
    flying its task on a depleted battery, which is reported as a ``Violation``.
    """
    reallocated = reallocate_low_battery_tasks(drones, threshold_pct)
    violations = [
        Violation(
            drone_ids=[drone.drone_id],
            timestamp_s=timestamp_s,
            measured_value=drone.battery_pct,
            threshold=threshold_pct,
            description=(
                f"{drone.drone_id} battery at {drone.battery_pct:.1f}% is below the "
                f"{threshold_pct:.1f}% threshold and still holds task {drone.task_id!r}; "
                "no replacement drone was available to reallocate it to"
            ),
        )
        for drone in reallocated
        if drone.battery_pct < threshold_pct and drone.task_id is not None
    ]
    return Verdict(passed=not violations, violations=violations)


SCENARIO = Scenario(
    name="battery_reallocation",
    description=(
        "A drone's battery drops below threshold mid-mission with an idle replacement "
        "available; its task should be reallocated rather than silently dropped."
    ),
    run=partial(_run, _DEFAULT_FLEET),
)
