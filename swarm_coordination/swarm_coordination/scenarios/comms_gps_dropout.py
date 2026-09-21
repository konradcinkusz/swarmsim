"""Comms/GPS dropout: a configurable percentage of drones lose link mid-mission.

Explicit degrade policy (stated here, not left implicit): a drone that loses
comms/GPS holds its last commanded position --- it freezes exactly where the
formation last commanded it (this scenario's setup is a fixed formation, so "last
commanded position" is simply its target in that formation) rather than continuing to
move, drifting, or being dropped from the swarm's position picture. The
formation-spacing invariant is then checked *only among the drones that are still
connected*: a disconnected drone contributes no separation check of its own, since it
is no longer receiving fresh commands to react to a closing neighbor, but any two
still-connected drones must still keep the configured minimum separation from each
other.

That per-pair spacing check alone is not the whole story: losing comms/GPS on too much
of the swarm is unsafe on its own, independent of whether the survivors still keep
separation, because "hold last commanded position" stops being a reasonable stand-in
for a real fallback once too few drones are left actually flying the mission. This
scenario therefore also checks the dropout fraction itself against a documented
maximum-safe-dropout threshold (``_MAX_SAFE_DROPOUT_FRACTION``) and reports a
``Violation`` when it is exceeded, on top of (not instead of) the spacing check --- so
a swarm that degrades catastrophically is flagged even if, by chance, its few
survivors happen to still be spaced apart.
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
_DROPOUT_TIMESTAMP_S = 20.0

# The maximum fraction of the swarm this scenario considers safe to lose comms/GPS on
# mid-mission; beyond this, "hold last commanded position" is no longer trusted as a
# safe degrade on its own, and the dropout itself is flagged as a Violation.
_MAX_SAFE_DROPOUT_FRACTION = 0.3

# A representative low dropout the swarm should absorb under the stated policy.
_DEFAULT_DROPOUT_FRACTION = 0.2

# Index 0 is the leader; 1..4 are the followers in v_formation()'s offset order.
_DRONE_IDS = ["leader", "follower_1", "follower_2", "follower_3", "follower_4"]


def _commanded_positions() -> list[Vector3]:
    """Leader plus its 4 V-formation followers, at their commanded target positions."""
    leader = Vector3(0.0, 0.0, 5.0)
    offsets = v_formation(count=_FOLLOWER_COUNT, spacing_m=_SPACING_M)
    return [leader, *follower_targets(leader, offsets)]


def _dropped_ids(dropout_fraction: float, drone_ids: Sequence[str]) -> list[str]:
    """The drones that lose comms/GPS for ``dropout_fraction``, chosen deterministically.

    Drops from the front of ``drone_ids`` (the leader first, then followers in order)
    so a given ``dropout_fraction`` always drops the same drones --- this scenario
    evaluates the degrade *policy*, not which specific drone happens to get unlucky.
    """
    if not 0.0 <= dropout_fraction <= 1.0:
        raise ValueError("dropout_fraction must be between 0.0 and 1.0")
    dropped_count = round(dropout_fraction * len(drone_ids))
    return list(drone_ids[:dropped_count])


def _closest_pair(positions: Sequence[Vector3]) -> tuple[int, int]:
    """Indices of the two closest positions; ``positions`` must hold at least two."""
    return min(
        combinations(range(len(positions)), 2),
        key=lambda pair: positions[pair[0]].distance_to(positions[pair[1]]),
    )


def _run(
    dropout_fraction: float,
    min_separation_m: float = _MIN_SEPARATION_M,
    max_safe_dropout_fraction: float = _MAX_SAFE_DROPOUT_FRACTION,
    timestamp_s: float = _DROPOUT_TIMESTAMP_S,
) -> Verdict:
    """Drop ``dropout_fraction`` of the swarm mid-mission and check the degrade policy.

    Per the policy documented at module level: dropped drones freeze at their last
    commanded position and are excluded from the formation-spacing invariant, which is
    then checked only among the still-connected drones; separately, a
    ``dropout_fraction`` exceeding ``max_safe_dropout_fraction`` is itself reported as
    a ``Violation``. Either check, independently, can add a ``Violation`` to the
    result.
    """
    dropped = _dropped_ids(dropout_fraction, _DRONE_IDS)
    dropped_set = set(dropped)
    violations: list[Violation] = []

    if dropout_fraction > max_safe_dropout_fraction:
        violations.append(
            Violation(
                drone_ids=dropped,
                timestamp_s=timestamp_s,
                measured_value=dropout_fraction,
                threshold=max_safe_dropout_fraction,
                description=(
                    f"{len(dropped)}/{len(_DRONE_IDS)} drones ({dropout_fraction:.0%}) "
                    "lost comms/GPS, exceeding the "
                    f"{max_safe_dropout_fraction:.0%} maximum safe dropout fraction"
                ),
            )
        )

    connected = [
        (drone_id, position)
        for drone_id, position in zip(_DRONE_IDS, _commanded_positions(), strict=True)
        if drone_id not in dropped_set
    ]
    connected_positions = [position for _, position in connected]
    separation = min_separation(connected_positions)
    if separation is not None and separation < min_separation_m:
        i, j = _closest_pair(connected_positions)
        id_a, id_b = connected[i][0], connected[j][0]
        violations.append(
            Violation(
                drone_ids=[id_a, id_b],
                timestamp_s=timestamp_s,
                measured_value=separation,
                threshold=min_separation_m,
                description=(
                    f"{id_a} and {id_b} closed to {separation:.2f}m among the "
                    "still-connected drones after comms/GPS dropout, below the "
                    f"{min_separation_m:.2f}m formation-spacing minimum"
                ),
            )
        )

    return Verdict(passed=not violations, violations=violations)


SCENARIO = Scenario(
    name="comms_gps_dropout",
    description=(
        "A configurable percentage of drones lose comms/GPS mid-mission and hold "
        "their last commanded position; the formation-spacing invariant is then "
        "checked only among the drones still connected, and the dropout fraction "
        f"itself is checked against a {_MAX_SAFE_DROPOUT_FRACTION:.0%} "
        f"maximum-safe-dropout threshold. Default configured at a "
        f"{_DEFAULT_DROPOUT_FRACTION:.0%} dropout, which the swarm should absorb."
    ),
    run=partial(_run, _DEFAULT_DROPOUT_FRACTION),
)
