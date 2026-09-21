"""Waypoint-queue advance logic: which waypoint a drone currently pursues, and when it
has "arrived" (within tolerance) so the queue advances to the next one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .trajectory import Vector3, step_towards


@dataclass
class WaypointQueue:
    waypoints: Sequence[Vector3]
    tolerance_m: float = 0.5
    _index: int = field(default=0, init=False, repr=False)

    @property
    def current(self) -> Vector3 | None:
        if self._index >= len(self.waypoints):
            return None
        return self.waypoints[self._index]

    @property
    def is_complete(self) -> bool:
        return self._index >= len(self.waypoints)

    @property
    def remaining(self) -> int:
        return max(0, len(self.waypoints) - self._index)

    def advance(self, position: Vector3) -> bool:
        """Advance past the current waypoint if ``position`` is within tolerance.

        Returns True if the queue advanced (including completing).
        """
        target = self.current
        if target is None:
            return False
        if position.distance_to(target) <= self.tolerance_m:
            self._index += 1
            return True
        return False

    def step(self, position: Vector3, max_step: float) -> Vector3:
        """Advance the queue if arrived, then return the next commanded position.

        Once the queue is complete, holds the drone at its last known position rather
        than returning an undefined target.
        """
        self.advance(position)
        target = self.current
        if target is None:
            return position
        return step_towards(position, target, max_step)
