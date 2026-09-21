"""Scale scenario: collision-check cost across drone counts.

Runs the same formation/collision-check logic (``has_collision``/``min_separation``
from ``formation.py``, an O(n^2) pairwise check) at a small drone count and a larger
one. Checks that collision-check correctness holds at both scales, and that the
number of pairwise comparisons the check performs grows roughly with n^2 between
them --- a deterministic, closed-form proxy for check cost (``drone_count`` choose 2,
the same ``i in range(n)`` / ``j in range(i + 1, n)`` shape ``min_separation`` walks),
not wall-clock timing, which is flaky in CI.

5 vs. 25 followers (6 vs. 26 drones once the leader is included) is picked to stay
fast in CI --- nowhere near 50 drones --- while the ~4.3x growth in drone count still
produces a clearly super-linear, ~n^2-ish jump in comparisons (15 vs. 325, ~21.7x)
that a linear check could not produce.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations

from ..formation import follower_targets, has_collision, min_separation, v_formation
from ..trajectory import Vector3
from . import Scenario, Verdict, Violation

_MIN_SEPARATION_M = 1.0
_SMALL_FOLLOWER_COUNT = 5
_LARGE_FOLLOWER_COUNT = 25
_SCALE_TIMESTAMP_S = 0.0
# A linear check would grow comparisons by ~(drones_large / drones_small), ~4.3x,
# between the two default counts; this sits well above that so only genuinely
# super-linear (~n^2) growth passes, without pinning the exact ratio.
_MIN_EXPECTED_GROWTH_RATIO = 15.0


def _drone_ids(follower_count: int) -> list[str]:
    """Ids for a leader plus ``follower_count`` followers, in ``_formation_positions`` order."""
    return ["leader"] + [f"follower_{i}" for i in range(1, follower_count + 1)]


def _formation_positions(follower_count: int) -> list[Vector3]:
    """A leader plus ``follower_count`` followers in a V formation, spacing_m=2.0."""
    leader = Vector3(0.0, 0.0, 5.0)
    offsets = v_formation(count=follower_count, spacing_m=2.0)
    return [leader, *follower_targets(leader, offsets)]


def _closest_pair(positions: Sequence[Vector3]) -> tuple[int, int]:
    """Indices of the two closest positions; ``positions`` must hold at least two."""
    return min(
        combinations(range(len(positions)), 2),
        key=lambda pair: positions[pair[0]].distance_to(positions[pair[1]]),
    )


def _pairwise_comparison_count(drone_count: int) -> int:
    """Comparisons the pairwise nested loop in ``min_separation`` performs for ``drone_count``.

    The closed form (``drone_count`` choose 2) of its ``i in range(n)``, ``j in
    range(i + 1, n)`` nesting, computed directly rather than re-deriving the distance
    math ``min_separation`` already owns.
    """
    return drone_count * (drone_count - 1) // 2


def _check_scale(
    follower_count: int, min_separation_m: float, timestamp_s: float
) -> Violation | None:
    """Build a ``follower_count``-follower formation and check it against ``min_separation_m``.

    Reuses ``has_collision``/``min_separation`` for the pass/fail value and the
    measured distance; only identifying *which* pair of drones is closest is local to
    this scenario, since neither reports the offending indices.
    """
    positions = _formation_positions(follower_count)
    if not has_collision(positions, min_separation_m):
        return None

    separation = min_separation(positions)
    ids = _drone_ids(follower_count)
    i, j = _closest_pair(positions)
    return Violation(
        drone_ids=[ids[i], ids[j]],
        timestamp_s=timestamp_s,
        measured_value=separation if separation is not None else 0.0,
        threshold=min_separation_m,
        description=(
            f"{ids[i]} and {ids[j]} closed to {separation:.2f}m in the "
            f"{follower_count}-follower formation, below the {min_separation_m:.2f}m minimum"
        ),
    )


def _growth_violation(
    small_follower_count: int, large_follower_count: int, timestamp_s: float
) -> Violation | None:
    """Flag it if pairwise-comparison count didn't grow ~quadratically between the two scales."""
    small_comparisons = _pairwise_comparison_count(small_follower_count + 1)
    large_comparisons = _pairwise_comparison_count(large_follower_count + 1)
    growth_ratio = large_comparisons / small_comparisons
    if growth_ratio >= _MIN_EXPECTED_GROWTH_RATIO:
        return None
    return Violation(
        drone_ids=[],
        timestamp_s=timestamp_s,
        measured_value=growth_ratio,
        threshold=_MIN_EXPECTED_GROWTH_RATIO,
        description=(
            f"pairwise comparison count only grew {growth_ratio:.1f}x between "
            f"{small_follower_count} and {large_follower_count} followers, short of the "
            f"{_MIN_EXPECTED_GROWTH_RATIO:.1f}x expected for ~n^2 scaling"
        ),
    )


def _run(
    small_follower_count: int = _SMALL_FOLLOWER_COUNT,
    large_follower_count: int = _LARGE_FOLLOWER_COUNT,
    min_separation_m: float = _MIN_SEPARATION_M,
    timestamp_s: float = _SCALE_TIMESTAMP_S,
) -> Verdict:
    """Check collision-check correctness at two scales, and comparison-count growth between them.

    Both formations are held with zero perturbation, so with a real
    ``min_separation_m`` threshold neither should ever report a collision --- this
    exercises ``has_collision``/``min_separation`` giving the right (negative) answer
    at both scales. Growth is checked against the closed-form comparison count for the
    same O(n^2) shape, not wall-clock timing, which is flaky in CI.
    """
    violations = [
        violation
        for follower_count in (small_follower_count, large_follower_count)
        if (violation := _check_scale(follower_count, min_separation_m, timestamp_s)) is not None
    ]

    growth_violation = _growth_violation(small_follower_count, large_follower_count, timestamp_s)
    if growth_violation is not None:
        violations.append(growth_violation)

    return Verdict(passed=not violations, violations=violations)


SCENARIO = Scenario(
    name="scale_collision_check",
    description=(
        "Runs the O(n^2) has_collision/min_separation pairwise check at "
        f"{_SMALL_FOLLOWER_COUNT} and {_LARGE_FOLLOWER_COUNT} followers: checks "
        "correctness at both scales and that pairwise-comparison count grows roughly "
        "with n^2 between them (a deterministic proxy for check cost, not wall-clock "
        "timing)."
    ),
    run=_run,
)
