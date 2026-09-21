"""Scenario: two independently-planned sub-swarms merge along crossing trajectories.

Each sub-swarm flies its own straight-line leader path, with the rest of its drones
held in formation off that leader via ``formation.follower_targets`` (see
``formation.py``). ``_check_merge`` is the general checker, shared by the default
(safe) scenario below and by this module's tests: it samples every sub-swarm's
positions at evenly spaced points across the merge and flags any pair of drones —
whether from the same or different sub-swarms — that ever comes within
``min_separation_m`` of each other, attributing each breach to the concrete pair of
drone ids and the timestamp it happened at.

The exported ``SCENARIO`` flies its two sub-swarms with a 3m altitude offset while
their ground tracks cross — real spare capacity a merge planner has and a naive
same-altitude merge would leave on the table — so it always passes. A same-altitude,
genuinely colliding configuration is exercised directly in this module's tests via
``_check_merge``, to prove detection and attribution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..formation import follower_targets, line_formation
from ..trajectory import Vector3
from . import Scenario, Verdict, Violation

_MIN_SEPARATION_M = 2.0
_SAMPLE_COUNT = 21
_MERGE_DURATION_S = 10.0


@dataclass(frozen=True)
class _SubSwarm:
    """A group of drones flying formation off a single straight-line leader path.

    ``drone_ids`` has one id for the leader followed by one id per entry in
    ``offsets``, matching the order ``positions_at`` returns them in.
    """

    drone_ids: Sequence[str]
    start: Vector3
    end: Vector3
    offsets: Sequence[Vector3]

    def positions_at(self, t: float) -> list[Vector3]:
        """Absolute positions of every drone in this sub-swarm at fraction ``t`` (in
        ``[0, 1]``) of the way along the straight line from ``start`` to ``end``."""
        leader = self.start + (self.end - self.start).scale(t)
        return [leader, *follower_targets(leader, self.offsets)]


def _check_merge(
    sub_swarms: Sequence[_SubSwarm],
    min_separation_m: float = _MIN_SEPARATION_M,
    sample_count: int = _SAMPLE_COUNT,
    duration_s: float = _MERGE_DURATION_S,
) -> Verdict:
    """Fly all ``sub_swarms`` along their independent leader trajectories together and
    check that no two drones — whether from the same or different sub-swarms — ever
    come within ``min_separation_m`` of each other.

    Positions are sampled at ``sample_count`` evenly spaced points across the merge;
    normalized time ``t`` in ``[0, 1]`` is reported as ``t * duration_s`` seconds so a
    ``Violation.timestamp_s`` lines up with a wall-clock merge duration.
    """
    violations: list[Violation] = []
    steps = max(sample_count, 1)
    for step in range(steps):
        t = step / (steps - 1) if steps > 1 else 0.0
        timestamp_s = t * duration_s

        drone_ids: list[str] = []
        positions: list[Vector3] = []
        for sub_swarm in sub_swarms:
            drone_ids.extend(sub_swarm.drone_ids)
            positions.extend(sub_swarm.positions_at(t))

        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                distance = positions[i].distance_to(positions[j])
                if distance < min_separation_m:
                    violations.append(
                        Violation(
                            drone_ids=[drone_ids[i], drone_ids[j]],
                            timestamp_s=timestamp_s,
                            measured_value=distance,
                            threshold=min_separation_m,
                            description=(
                                f"{drone_ids[i]} and {drone_ids[j]} breached minimum "
                                "separation during sub-swarm merge"
                            ),
                        )
                    )
    return Verdict(passed=not violations, violations=violations)


def _run() -> Verdict:
    """Two 2-drone sub-swarms cross ground tracks while merging, flown 3m apart in
    altitude — enough vertical clearance that the horizontal crossing never breaches
    minimum separation. Should always pass."""
    sub_swarm_a = _SubSwarm(
        drone_ids=["sub_a_leader", "sub_a_follower"],
        start=Vector3(-10.0, 0.0, 5.0),
        end=Vector3(10.0, 0.0, 5.0),
        offsets=line_formation(1, spacing_m=3.0),
    )
    sub_swarm_b = _SubSwarm(
        drone_ids=["sub_b_leader", "sub_b_follower"],
        start=Vector3(0.0, -10.0, 8.0),
        end=Vector3(0.0, 10.0, 8.0),
        offsets=line_formation(1, spacing_m=3.0),
    )
    return _check_merge([sub_swarm_a, sub_swarm_b])


SCENARIO = Scenario(
    name="subswarm_merge_no_collision",
    description=(
        "Two 2-drone sub-swarms merge on crossing ground tracks, separated by 3m of "
        "altitude; checks no pair of drones (within or across sub-swarms) breaches "
        "minimum separation during the merge. Always passes."
    ),
    run=_run,
)
