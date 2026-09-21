"""MCP server exposing swarm-level tools over SwarmApi.Api's existing REST surface —
see docs/adr/0005-mcp-server-and-bearer-auth.md for why this wraps the REST API rather
than talking to ROS 2/rosbridge directly, and why it stops at two tools for now.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from mcp_server.swarm_client import Waypoint, fetch_swarm_status, submit_mission

mcp = FastMCP("swarmsim")


def _base_url() -> str:
    return os.environ.get("SWARM_API_BASE_URL", "http://localhost:5000")


@mcp.tool()
def get_swarm_status() -> dict:
    """Current swarm state: every drone's position, battery, status, and the active
    mission. Always unauthenticated, in both Open and Enforced auth mode."""
    return fetch_swarm_status(_base_url())


@mcp.tool()
def start_mission(
    name: str,
    mission_type: str,
    waypoints: list[dict[str, float]],
    drone_count: int,
    spacing_meters: float = 2.0,
) -> dict:
    """Dispatch a mission to the swarm. `mission_type` is "waypoint" or "formation" —
    formation reuses this same tool, since SwarmApi.Domain.Formation already computes
    the leader-follower offsets server-side. Requires SWARM_API_TOKEN to be set once
    SwarmApi.Api runs in Enforced auth mode; unset is fine in Open mode."""
    token = os.environ.get("SWARM_API_TOKEN")
    parsed_waypoints = [Waypoint(w["x"], w["y"], w["z"]) for w in waypoints]
    return submit_mission(
        _base_url(), name, mission_type, parsed_waypoints, drone_count, spacing_meters, token
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
