"""Swarm-wide overrides, as PX4 flight modes.

The API's /swarm/command (contracts/rosbridge/swarm_command.v1.schema.json) names what
the swarm should do instead of its mission; PX4 already implements each of those as an
autonomous mode, so a drone hands control back to its autopilot rather than flying the
manoeuvre itself from offboard setpoints. No rclpy: unit tested without ROS.
"""

from __future__ import annotations

PX4_MODE_FOR_COMMAND = {
    "rtl": "AUTO.RTL",
    "land": "AUTO.LAND",
    "hold": "AUTO.LOITER",
}


def mode_for_command(command: str) -> str:
    try:
        return PX4_MODE_FOR_COMMAND[command]
    except KeyError:
        raise ValueError(
            f"unknown swarm command {command!r}, expected one of {sorted(PX4_MODE_FOR_COMMAND)}"
        ) from None
