"""MCP server exposing SwarmApi.Api's REST endpoints as MCP tools.

Proof-of-concept for GitHub issue #20. Both tools are thin wrappers: they take the
same fields as the corresponding SwarmApi.Api REST endpoint, call it over HTTP, and
hand back its JSON response. No mission/swarm business logic lives here -- that stays
in `backend/src/SwarmApi.Application` and `SwarmApi.Domain`, per this repo's
`CLAUDE.md` ("Program.cs stays a manifest ... business logic goes in
SwarmApi.Application/SwarmApi.Domain, not in the endpoint handlers") applied to this
adapter the same way.

Endpoints wrapped (see the root README's Quickstart/Tutorial sections for the exact
request/response JSON shapes, and
`backend/src/SwarmApi.Application/Contracts/CreateMissionRequest.cs` /
`backend/src/SwarmApi.Domain/{Mission,SwarmState}.cs` for the wire contracts):

- POST /api/missions   -> create_mission
- GET  /api/swarm/state -> get_swarm_state

Target API base URL is read from the SWARM_API_URL environment variable (default
http://localhost:5000) -- see README.md in this directory for how to run this server
against a local SwarmApi.Api instance.
"""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

SWARM_API_URL = os.environ.get("SWARM_API_URL", "http://localhost:5000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("SWARM_API_TIMEOUT_SECONDS", "10.0"))

mcp = FastMCP(
    "swarmsim-mcp-server",
    instructions=(
        "Thin MCP wrapper over SwarmApi.Api's mission and swarm-state REST "
        "endpoints. Requires a reachable SwarmApi.Api instance -- see "
        "SWARM_API_URL."
    ),
)


class Waypoint(BaseModel):
    """A single waypoint, matching `WaypointDto` (X, Y, Z in meters, local ENU frame)."""

    x: float
    y: float
    z: float


def _api_error(response: httpx.Response) -> RuntimeError:
    return RuntimeError(
        f"SwarmApi.Api returned {response.status_code} for "
        f"{response.request.method} {response.request.url}: {response.text}"
    )


@mcp.tool()
async def create_mission(
    name: str,
    mission_type: str = Field(
        description='Mission type: "waypoint" or "formation" (the request body\'s "type" field).'
    ),
    waypoints: list[Waypoint] = Field(
        description="Ordered list of {x, y, z} waypoints, in meters (local ENU frame)."
    ),
    drone_count: int = Field(description="Number of drones to assign to this mission."),
    spacing_meters: float = 2.0,
) -> dict:
    """Create a swarm mission by calling POST /api/missions on SwarmApi.Api.

    Same fields as the REST request body (`CreateMissionRequest`): name, type,
    waypoints, droneCount, spacingMeters. Returns the created `Mission` JSON
    (id, name, type, waypoints, droneCount, spacingMeters, createdAtUtc) exactly as
    SwarmApi.Api returns it on 201 Created. Raises if SwarmApi.Api rejects the
    request (e.g. 400 with validation errors) or cannot be reached.
    """
    payload = {
        "name": name,
        "type": mission_type,
        "waypoints": [w.model_dump() for w in waypoints],
        "droneCount": drone_count,
        "spacingMeters": spacing_meters,
    }
    async with httpx.AsyncClient(base_url=SWARM_API_URL, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post("/api/missions", json=payload)
    if response.status_code >= 400:
        raise _api_error(response)
    return response.json()


@mcp.tool()
async def get_swarm_state() -> dict:
    """Fetch the current swarm state by calling GET /api/swarm/state on SwarmApi.Api.

    Takes no arguments. Returns the `SwarmState` JSON exactly as SwarmApi.Api
    returns it (drones, activeMissionId, timestampUtc, bridgeMode). Raises if
    SwarmApi.Api returns an error status or cannot be reached.
    """
    async with httpx.AsyncClient(base_url=SWARM_API_URL, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get("/api/swarm/state")
    if response.status_code >= 400:
        raise _api_error(response)
    return response.json()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
