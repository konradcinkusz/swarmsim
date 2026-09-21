"""Leader-follower formation offsets and separation checking (M2).

A formation is a plain list of leader-relative ``Vector3`` offsets — a new shape is a
new function returning such a list, never a new branch in the code that consumes it.
"""

from __future__ import annotations

from collections.abc import Sequence

from .trajectory import Vector3


def line_formation(count: int, spacing_m: float = 2.0) -> list[Vector3]:
    """Offsets for ``count`` followers in a line directly behind the leader."""
    if count < 0:
        raise ValueError("count must be non-negative")
    return [Vector3(-spacing_m * (i + 1), 0.0, 0.0) for i in range(count)]


def v_formation(count: int, spacing_m: float = 2.0) -> list[Vector3]:
    """Offsets for ``count`` followers in a V behind the leader, alternating sides."""
    if count < 0:
        raise ValueError("count must be non-negative")
    offsets: list[Vector3] = []
    for i in range(count):
        rank = i // 2 + 1
        side = 1 if i % 2 == 0 else -1
        offsets.append(Vector3(-spacing_m * rank, side * spacing_m * rank, 0.0))
    return offsets


def follower_targets(leader_position: Vector3, offsets: Sequence[Vector3]) -> list[Vector3]:
    """Absolute target positions for each follower, given the leader's current position.

    Offsets are axis-aligned and leader-relative for this phase — rotating the offset
    set by the leader's heading is a documented follow-up once missions carry a real
    heading, not a gap being silently assumed away.
    """
    return [leader_position + offset for offset in offsets]


def min_separation(positions: Sequence[Vector3]) -> float | None:
    """The smallest pairwise distance among ``positions``, or None if fewer than two."""
    if len(positions) < 2:
        return None
    best: float | None = None
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            distance = positions[i].distance_to(positions[j])
            if best is None or distance < best:
                best = distance
    return best


def has_collision(positions: Sequence[Vector3], min_distance_m: float) -> bool:
    """True if any two drones are closer than ``min_distance_m`` — M2's no-collision check."""
    separation = min_separation(positions)
    return separation is not None and separation < min_distance_m
