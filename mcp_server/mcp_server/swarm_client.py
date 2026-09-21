"""Pure request-building, plus the thin I/O that uses it, for talking to SwarmApi.Api's
existing REST surface. Split the way swarm_coordination splits nodes/ from
trajectory.py/formation.py: the pure functions below are unit tested with no running
SwarmApi.Api and no network; fetch_swarm_status/submit_mission are not, the same way
swarm_coordination's ROS node adapters aren't — see swarm_coordination/README.md.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Waypoint:
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


def build_mission_payload(
    name: str,
    mission_type: str,
    waypoints: list[Waypoint],
    drone_count: int,
    spacing_meters: float = 2.0,
) -> dict[str, Any]:
    """Mirrors SwarmApi.Application.Contracts.CreateMissionRequest's wire shape —
    camelCase field names, ASP.NET Core minimal APIs' default JSON policy."""
    return {
        "name": name,
        "type": mission_type,
        "waypoints": [w.to_dict() for w in waypoints],
        "droneCount": drone_count,
        "spacingMeters": spacing_meters,
    }


def build_status_request(base_url: str) -> urllib.request.Request:
    return urllib.request.Request(f"{base_url.rstrip('/')}/api/swarm/state", method="GET")


def build_mission_request(
    base_url: str, payload: dict[str, Any], token: str | None = None
) -> urllib.request.Request:
    """`token` is a bearer token the operator already obtained from authservice — this
    module never logs in on its own behalf. See
    docs/adr/0005-mcp-server-and-bearer-auth.md. Omitted entirely when `token` is falsy,
    matching SwarmApi.Api's Open mode, which needs no Authorization header at all."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return urllib.request.Request(
        f"{base_url.rstrip('/')}/api/missions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def fetch_swarm_status(base_url: str) -> dict[str, Any]:
    with urllib.request.urlopen(build_status_request(base_url)) as response:
        return json.load(response)


def submit_mission(
    base_url: str,
    name: str,
    mission_type: str,
    waypoints: list[Waypoint],
    drone_count: int,
    spacing_meters: float = 2.0,
    token: str | None = None,
) -> dict[str, Any]:
    payload = build_mission_payload(name, mission_type, waypoints, drone_count, spacing_meters)
    with urllib.request.urlopen(build_mission_request(base_url, payload, token)) as response:
        return json.load(response)
