"""Pure position math shared by waypoint following and formation control.

No ROS, no I/O — this module has no `rclpy` import and is safe to unit test without a
ROS 2 installation. See ``nodes/`` for the thin adapters that call into it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Vector3:
    x: float
    y: float
    z: float

    def __add__(self, other: Vector3) -> Vector3:
        return Vector3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vector3) -> Vector3:
        return Vector3(self.x - other.x, self.y - other.y, self.z - other.z)

    def scale(self, factor: float) -> Vector3:
        return Vector3(self.x * factor, self.y * factor, self.z * factor)

    def norm(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def distance_to(self, other: Vector3) -> float:
        return (self - other).norm()


def step_towards(current: Vector3, target: Vector3, max_step: float) -> Vector3:
    """Move ``current`` towards ``target`` by at most ``max_step``.

    Returns ``target`` exactly (not asymptotically) once within ``max_step`` of it, so
    a fixed-rate caller reaches the target in a finite, predictable number of calls.
    """
    if max_step <= 0:
        raise ValueError("max_step must be positive")
    delta = target - current
    distance = delta.norm()
    if distance <= max_step:
        return target
    return current + delta.scale(max_step / distance)
