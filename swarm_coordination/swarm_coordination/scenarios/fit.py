"""How closely drones fly a formation, whichever of them leads and whoever takes which slot.

A mission message names a formation, a drone count and a spacing. It does not say who
leads or who takes which slot: that is the swarm's decision, and the reference swarm's
(the lowest ids, in id order) is only one policy. So a check on the formation should judge
the shape the drones make. ``fit_formation`` finds the closest fit: some drone as the apex,
the others matched one-to-one to the slots around it, with the *largest* distance of any
drone from its slot as small as it can be. That distance is the smallest ``max_m`` the
formation would pass.

Pure, and independent of the simulator: it takes positions and offsets, so it is tested
against brute force. Offsets are axis-aligned and leader-relative (formation.py).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..trajectory import Vector3


@dataclass(frozen=True)
class Fit:
    error_m: float  # the largest follower error in the closest fit
    leader: str
    slots: dict[str, int]  # follower -> the index of its slot in ``offsets``
    errors: dict[str, float]  # follower -> its distance from that slot


def _perfect_matching(allowed: Sequence[Sequence[bool]]) -> list[int] | None:
    """A row -> column matching that uses only allowed pairs and covers every row."""
    size = len(allowed)
    row_of = [-1] * size  # row_of[column]: the row holding it

    def augment(row: int, seen: list[bool]) -> bool:
        for column in range(size):
            if allowed[row][column] and not seen[column]:
                seen[column] = True
                if row_of[column] < 0 or augment(row_of[column], seen):
                    row_of[column] = row
                    return True
        return False

    for row in range(size):
        if not augment(row, [False] * size):
            return None
    assignment = [0] * size
    for column, row in enumerate(row_of):
        assignment[row] = column
    return assignment


def bottleneck_assignment(cost: Sequence[Sequence[float]]) -> tuple[float, list[int]]:
    """The one-to-one row -> column assignment whose largest cost is smallest, with that cost.

    Binary search over the distinct costs for the smallest threshold at which the pairs
    within it still match every row. ``cost`` is square.
    """
    size = len(cost)
    if size == 0:
        return 0.0, []
    if any(len(row) != size for row in cost):
        raise ValueError("the cost matrix must be square")
    thresholds = sorted({value for row in cost for value in row})
    low, high = 0, len(thresholds) - 1  # every pair is allowed at thresholds[high]
    while low < high:
        middle = (low + high) // 2
        allowed = [[value <= thresholds[middle] for value in row] for row in cost]
        if _perfect_matching(allowed) is not None:
            high = middle
        else:
            low = middle + 1
    allowed = [[value <= thresholds[low] for value in row] for row in cost]
    assignment = _perfect_matching(allowed)
    assert assignment is not None
    return thresholds[low], assignment


def fit_formation(
    positions: Mapping[str, Vector3], offsets: Sequence[Vector3], leader: str | None = None
) -> Fit:
    """The closest fit of the drones in ``positions`` to the formation ``offsets``.

    One drone more than there are offsets: the leader and a follower for every slot. With
    ``leader`` given, that drone is the apex; otherwise each drone is tried, and a tie goes
    to the first in ``positions``' order.
    """
    if len(positions) != len(offsets) + 1:
        raise ValueError(f"{len(positions)} drone(s) for a leader and {len(offsets)} slot(s)")
    if leader is not None and leader not in positions:
        raise ValueError(f"{leader} is not among the drones")
    best: Fit | None = None
    for apex in [leader] if leader is not None else list(positions):
        followers = [d for d in positions if d != apex]
        cost = [
            [positions[d].distance_to(positions[apex] + offset) for offset in offsets]
            for d in followers
        ]
        error, assignment = bottleneck_assignment(cost)
        if best is None or error < best.error_m:
            slots = dict(zip(followers, assignment, strict=True))
            errors = {d: cost[row][slots[d]] for row, d in enumerate(followers)}
            best = Fit(error, apex, slots, errors)
    assert best is not None
    return best
