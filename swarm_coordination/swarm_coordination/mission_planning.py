"""Turns a dispatched mission into per-drone assignments, and reads the rosbridge contract.

Pure and rclpy-free: `nodes/mission_dispatcher_node.py` deserializes the incoming message
with :func:`parse_mission_payload`, calls :func:`plan_mission`, and publishes the result.
The payloads are the ones in contracts/rosbridge/ (tested against the same example files
as the .NET side). Waypoints and formation offsets are in the shared world frame.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from .formation import line_formation, v_formation
from .trajectory import Vector3

CONTRACT_VERSION = 1
FORMATIONS = {"line": line_formation, "v": v_formation}
COMMANDS = ("rtl", "land", "hold")


@dataclass(frozen=True)
class MissionMessage:
    """A parsed /swarm/mission payload (contracts/rosbridge/swarm_mission.v1.schema.json)."""

    mission_id: str
    mission_type: str
    formation: str
    waypoints: list[Vector3]
    drone_count: int
    spacing_m: float


@dataclass(frozen=True)
class CommandMessage:
    """A parsed /swarm/command payload (contracts/rosbridge/swarm_command.v1.schema.json)."""

    command: str
    mission_id: str | None


@dataclass
class MissionPlan:
    """Who does what: explicit paths for some drones, a leader-relative slot for the rest."""

    mission_id: str
    paths: dict[str, list[Vector3]] = field(default_factory=dict)
    followers: dict[str, tuple[str, Vector3]] = field(default_factory=dict)

    @property
    def drones(self) -> list[str]:
        return sorted([*self.paths, *self.followers], key=lambda d: int(d.split("_")[1]))


def _require_version(payload: dict) -> None:
    if payload.get("version") != CONTRACT_VERSION:
        raise ValueError(f"unsupported contract version {payload.get('version')!r}")


def _require_uuid(value: object, name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ValueError(f"{name} must be a UUID, got {value!r}") from None


def parse_mission_payload(data: str) -> MissionMessage:
    """Validates and parses a /swarm/mission payload; raises ValueError on anything else."""
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"mission payload is not JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError("mission payload must be a JSON object")
    _require_version(payload)
    try:
        mission_type = payload["type"]
        formation = payload.get("formation", "line")
        waypoints = [Vector3(*(float(c) for c in wp)) for wp in payload["waypoints"]]
        drone_count = int(payload["drone_count"])
        spacing_m = float(payload["spacing_m"])
        mission_id = _require_uuid(payload["mission_id"], "mission_id")
    except KeyError as missing:
        raise ValueError(f"mission payload is missing {missing}") from None
    except TypeError as exc:
        raise ValueError(f"mission payload has a malformed field: {exc}") from None
    if mission_type not in ("waypoint", "formation"):
        raise ValueError(f"unknown mission type {mission_type!r}")
    if formation not in FORMATIONS:
        raise ValueError(f"unknown formation {formation!r}")
    return MissionMessage(mission_id, mission_type, formation, waypoints, drone_count, spacing_m)


def parse_command_payload(data: str) -> CommandMessage:
    """Validates and parses a /swarm/command payload; raises ValueError on anything else."""
    try:
        payload = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"command payload is not JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError("command payload must be a JSON object")
    _require_version(payload)
    command = payload.get("command")
    if command not in COMMANDS:
        raise ValueError(f"unknown command {command!r}")
    mission_id = payload.get("mission_id")
    if mission_id is not None:
        mission_id = _require_uuid(mission_id, "mission_id")
    return CommandMessage(command, mission_id)


def plan_swarm_waypoints(
    mission_type: str,
    base_waypoints: list[Vector3],
    drone_count: int,
    spacing_m: float,
) -> dict[str, list[Vector3]]:
    """Which drones get an explicit waypoint list for this mission, and what it is.

    'waypoint': every drone gets `base_waypoints` shifted onto its own parallel lane
    (y + i * spacing), so the swarm moves as a group without converging onto one line.

    'formation': only the leader (`drone_1`) gets `base_waypoints`, verbatim. Followers
    get no waypoint list at all — they hold a slot relative to the leader instead (see
    :func:`plan_mission`).
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


def plan_mission(mission: MissionMessage) -> MissionPlan:
    """Every drone's part in ``mission``: a path, or a slot behind the leader."""
    plan = MissionPlan(
        mission_id=mission.mission_id,
        paths=plan_swarm_waypoints(
            mission.mission_type, mission.waypoints, mission.drone_count, mission.spacing_m
        ),
    )
    if mission.mission_type == "formation":
        offsets = FORMATIONS[mission.formation](mission.drone_count - 1, mission.spacing_m)
        for i, offset in enumerate(offsets):
            plan.followers[f"drone_{i + 2}"] = ("drone_1", offset)
    return plan
