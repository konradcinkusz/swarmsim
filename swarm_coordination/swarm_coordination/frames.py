"""The shared world frame, and each drone's local frame inside it.

Every PX4 instance reports and accepts positions (via MAVROS, ENU) relative to its own
local origin — wherever that drone spawned. Missions, formations and the swarm state are
all expressed in one *world* frame (the Gazebo world's ENU axes and origin), so anything
that combines drones converts through here: world = local + spawn offset. PX4's local
frame is aligned with east/north regardless of the heading the model spawned with, so the
offset is a pure translation. No rclpy: unit tested without ROS.
"""

from __future__ import annotations

from .trajectory import Vector3


def local_to_world(local: Vector3, spawn: Vector3) -> Vector3:
    """A position this drone reports in its own frame, in the shared world frame."""
    return local + spawn


def world_to_local(world: Vector3, spawn: Vector3) -> Vector3:
    """A world-frame target, in the frame this drone's setpoints are interpreted in."""
    return world - spawn


def parse_model_pose(pose: str) -> Vector3:
    """The translation part of a PX4_GZ_MODEL_POSE string (``x,y,z,roll,pitch,yaw``).

    Missing trailing components default to 0, as PX4's gz_bridge does.
    """
    parts = [p.strip() for p in pose.split(",") if p.strip() != ""]
    if not 1 <= len(parts) <= 6:
        raise ValueError(f"model pose must have 1-6 comma-separated numbers, got {pose!r}")
    values = [float(p) for p in parts] + [0.0] * (3 - min(len(parts), 3))
    return Vector3(values[0], values[1], values[2])
