"""Builds the /swarm/state payload (contracts/rosbridge/swarm_state.v1.schema.json).

`nodes/swarm_state_aggregator_node.py` keeps each drone's latest readings and calls
:func:`build_state_message` on a timer. A reading nobody has received stays None and goes
out as null — never a default that would look measured. No rclpy: unit tested without ROS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .trajectory import Vector3

CONTRACT_VERSION = 1


@dataclass
class DroneReadings:
    """The latest of everything the aggregator has heard about one drone."""

    position_world: Vector3 | None = None
    position_time_s: float | None = None
    armed: bool | None = None
    mode: str | None = None
    battery_pct: float | None = None
    mission_id: str | None = None
    waypoint_index: int | None = None
    waypoint_count: int | None = None
    complete: bool = False


def battery_percent(fraction: float | None) -> float | None:
    """sensor_msgs/BatteryState.percentage (0..1, NaN when unknown) as 0..100 or None."""
    if fraction is None or math.isnan(fraction) or fraction < 0:
        return None
    return round(min(fraction, 1.0) * 100.0, 1)


def mission_complete(
    readings: dict[str, DroneReadings], mission_id: str, drones: list[str]
) -> bool:
    """Every drone assigned to ``mission_id`` finished its part and is back on the ground."""
    if not drones:
        return False
    for drone in drones:
        r = readings.get(drone)
        if r is None or r.mission_id != mission_id or not r.complete or r.armed is not False:
            return False
    return True


def build_state_message(
    readings: dict[str, DroneReadings],
    now_s: float,
    mission_id: str | None = None,
    mission_drones: list[str] | None = None,
) -> dict:
    drones = []
    for drone_id in sorted(readings, key=lambda d: int(d.split("_")[1])):
        r = readings[drone_id]
        if r.position_world is None:
            continue  # x/y/z are required; a drone never heard from is not reported
        drones.append(
            {
                "id": drone_id,
                "x": r.position_world.x,
                "y": r.position_world.y,
                "z": r.position_world.z,
                "armed": r.armed,
                "mode": r.mode,
                "battery_pct": r.battery_pct,
                "age_s": None
                if r.position_time_s is None
                else round(max(0.0, now_s - r.position_time_s), 3),
                "waypoint_index": r.waypoint_index if r.mission_id == mission_id else None,
                "waypoint_count": r.waypoint_count if r.mission_id == mission_id else None,
            }
        )

    mission = None
    if mission_id is not None:
        mission = {
            "id": mission_id,
            "complete": mission_complete(readings, mission_id, mission_drones or []),
        }
    return {"version": CONTRACT_VERSION, "frame": "world_enu", "mission": mission, "drones": drones}
