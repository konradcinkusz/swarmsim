"""The shared world frame, and each drone's local frame inside it.

Every PX4 instance reports and accepts positions (via MAVROS, ENU) relative to its own
local origin. Missions, formations and the swarm state are all expressed in one *world*
frame (the Gazebo world's ENU axes and origin), so anything that combines drones converts
through here. PX4's local frame is aligned with east/north regardless of the heading the
model spawned with, so the conversion is a pure translation:

- **Horizontally** the local origin is where the drone spawned, so world = local + spawn.
- **Vertically** the local origin is *not* the pad. PX4 fixes the origin's altitude when
  its estimator first gets a GNSS fix, from whatever height it had integrated by then; in
  the SITL smoke, drones standing on their pads read between -1.9 m and +2.6 m. Heights
  are therefore taken relative to the drone's **home** — the local height PX4 records on
  the ground at boot, again whenever the drone has drifted on the ground, and at every
  arming — so world z = local z - home height + the pad's own height (spawn z).

No rclpy: unit tested without ROS.
"""

from __future__ import annotations

from .trajectory import Vector3


def local_to_world(local: Vector3, spawn: Vector3, home_height: float = 0.0) -> Vector3:
    """A position this drone reports in its own frame, in the shared world frame.

    ``home_height`` is the local z of the drone's home (MAVROS ``home_position/home``);
    0 until PX4 has reported one.
    """
    return Vector3(local.x + spawn.x, local.y + spawn.y, local.z - home_height + spawn.z)


def world_to_local(world: Vector3, spawn: Vector3, home_height: float = 0.0) -> Vector3:
    """A world-frame target, in the frame this drone's setpoints are interpreted in."""
    return Vector3(world.x - spawn.x, world.y - spawn.y, world.z - spawn.z + home_height)


def parse_model_pose(pose: str) -> Vector3:
    """The translation part of a PX4_GZ_MODEL_POSE string (``x,y,z,roll,pitch,yaw``).

    Missing trailing components default to 0, as PX4's gz_bridge does.
    """
    parts = [p.strip() for p in pose.split(",") if p.strip() != ""]
    if not 1 <= len(parts) <= 6:
        raise ValueError(f"model pose must have 1-6 comma-separated numbers, got {pose!r}")
    values = [float(p) for p in parts] + [0.0] * (3 - min(len(parts), 3))
    return Vector3(values[0], values[1], values[2])
