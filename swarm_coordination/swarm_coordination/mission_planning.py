"""Turns a dispatched mission into per-drone waypoint assignments.

Pure and rclpy-free: `nodes/mission_dispatcher_node.py` is the only caller, and it does
nothing but deserialize the incoming message, call this, and publish the result.
"""

from __future__ import annotations

from .trajectory import Vector3


def plan_swarm_waypoints(
    mission_type: str,
    base_waypoints: list[Vector3],
    drone_count: int,
    spacing_m: float,
) -> dict[str, list[Vector3]]:
    """Which drones get an explicit waypoint list for this mission, and what it is.

    'waypoint': every drone gets `base_waypoints` shifted onto its own parallel lane
    (matching `launch/spawn_swarm.launch.py`'s static default), so the swarm moves as a
    group without converging onto one line.

    'formation': only the leader (`drone_1`) gets `base_waypoints`, verbatim. Followers
    get no waypoint list at all — they continuously chase the leader's live position via
    `formation_commander_node`, which needs no per-mission message to do that.
    """
    if drone_count < 1:
        raise ValueError("drone_count must be >= 1")
    if not base_waypoints:
        raise ValueError("base_waypoints must not be empty")

    if mission_type == "formation":
        return {"drone_1": list(base_waypoints)}

    if mission_type != "waypoint":
        raise ValueError(
            f"unknown mission_type '{mission_type}', expected 'waypoint' or 'formation'"
        )

    return {
        f"drone_{i + 1}": [wp + Vector3(0.0, i * spacing_m, 0.0) for wp in base_waypoints]
        for i in range(drone_count)
    }
