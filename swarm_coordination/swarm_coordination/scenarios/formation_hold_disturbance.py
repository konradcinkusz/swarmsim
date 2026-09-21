"""Formation-hold under disturbance: wind drift / GPS position noise mid-mission.

Holds a leader-follower V formation and, mid-mission, displaces one or more drones by
a fixed vector standing in for wind drift or GPS position noise. The
formation-spacing invariant --- no two drones closer than the configured minimum
separation --- is then checked against the *disturbed* positions, the same invariant
``example_static_formation.py`` checks against undisturbed ones. Bounded noise (GPS
jitter, a light gust) that the ~2.8m nominal V-formation spacing can absorb should
leave the invariant intact; a displacement big enough to overwhelm that margin (a
strong gust, a GPS glitch) should still be caught, with the offending pair of drones,
the timestamp, and the measured separation reported in the ``Violation``.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import partial
from itertools import combinations

from ..formation import follower_targets, min_separation, v_formation
from ..trajectory import Vector3
from . import Scenario, Verdict, Violation

_MIN_SEPARATION_M = 1.0
_FOLLOWER_COUNT = 4
_SPACING_M = 2.0
_DISTURBANCE_TIMESTAMP_S = 12.5

# Index 0 is the leader; 1..4 are the followers in v_formation()'s offset order.
_DRONE_IDS = ["leader", "follower_1", "follower_2", "follower_3", "follower_4"]

# A representative bounded disturbance: light GPS jitter / wind drift on each
# follower, well inside what the ~2.8m nominal V-formation spacing can absorb.
_BOUNDED_NOISE_BY_INDEX: dict[int, Vector3] = {
    1: Vector3(0.15, -0.10, 0.05),
    2: Vector3(-0.10, 0.20, -0.05),
    3: Vector3(0.10, 0.10, 0.00),
    4: Vector3(-0.15, -0.15, 0.10),
}


def _commanded_positions() -> list[Vector3]:
    """Leader plus its 4 V-formation followers, at their commanded (undisturbed) targets."""
    leader = Vector3(0.0, 0.0, 5.0)
    offsets = v_formation(count=_FOLLOWER_COUNT, spacing_m=_SPACING_M)
    return [leader, *follower_targets(leader, offsets)]


def _apply_disturbance(
    positions: Sequence[Vector3], noise_by_index: dict[int, Vector3]
) -> list[Vector3]:
    """Displace each indexed position by its noise vector; every other position passes through.

    Models wind drift or GPS position noise applied mid-mission to specific drones ---
    index 0 is the leader, 1..N the followers, matching ``_DRONE_IDS``.
    """
    return [
        position + noise_by_index[i] if i in noise_by_index else position
        for i, position in enumerate(positions)
    ]


def _closest_pair(positions: Sequence[Vector3]) -> tuple[int, int]:
    """Indices of the two closest positions; ``positions`` must hold at least two."""
    return min(
        combinations(range(len(positions)), 2),
        key=lambda pair: positions[pair[0]].distance_to(positions[pair[1]]),
    )


def _run(
    noise_by_index: dict[int, Vector3],
    min_separation_m: float = _MIN_SEPARATION_M,
    timestamp_s: float = _DISTURBANCE_TIMESTAMP_S,
) -> Verdict:
    """Apply ``noise_by_index`` to the commanded formation and check spacing still holds.

    Reuses ``formation.min_separation`` for the invariant's pass/fail value; only
    identifying *which* pair of drones closed too far is local to this scenario, since
    ``min_separation`` reports the distance but not the offending indices.
    """
    disturbed = _apply_disturbance(_commanded_positions(), noise_by_index)
    separation = min_separation(disturbed)

    if separation is None or separation >= min_separation_m:
        return Verdict(passed=True)

    i, j = _closest_pair(disturbed)
    violation = Violation(
        drone_ids=[_DRONE_IDS[i], _DRONE_IDS[j]],
        timestamp_s=timestamp_s,
        measured_value=separation,
        threshold=min_separation_m,
        description=(
            f"{_DRONE_IDS[i]} and {_DRONE_IDS[j]} closed to {separation:.2f}m under "
            f"disturbance, below the {min_separation_m:.2f}m formation-spacing minimum"
        ),
    )
    return Verdict(passed=False, violations=[violation])


SCENARIO = Scenario(
    name="formation_hold_disturbance",
    description=(
        "A 4-follower V formation subjected to bounded per-drone wind-drift/GPS-noise "
        "displacement mid-mission; the formation-spacing invariant should still hold."
    ),
    run=partial(_run, _BOUNDED_NOISE_BY_INDEX),
)
