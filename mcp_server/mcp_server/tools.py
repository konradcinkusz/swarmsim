"""The MCP tools: what each one does, what it may change, and how it is classified.

Pure — no `mcp` import — so pytest checks every tool against mcp_server/BEHAVIOUR.md,
whose table is the normative classification (architecture-standards AI-EVALS §4: a tool
is write-classified because the table says so, never because of its name). `server.py`
registers exactly these functions, with exactly these annotations.

No tool approves a plan, and no tool dispatches a mission without an approval code: the
only way this server can make drones fly is `dispatch_mission`, with the single-use code a
person was given when they approved the plan (docs/adr/0009). The service enforces that
gate itself; nothing here is what makes it hold.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .swarm_client import SwarmClient, Waypoint, build_mission_payload

ABORT_ACTIONS = ("rtl", "land", "hold")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    classification: str  # read | plan | gated-write | safety-write — see BEHAVIOUR.md
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool
    endpoint: str  # "METHOD /path" on SwarmApi.Api
    run: Callable[..., dict[str, Any]]


def get_swarm_status(client: SwarmClient) -> dict[str, Any]:
    """Every drone's position, battery, armed state, flight mode and status, the active
    mission, and whether the swarm is connected at all (bridgeMode)."""
    return client.swarm_status()


def get_mission(client: SwarmClient, mission_id: str) -> dict[str, Any]:
    """One mission and its status: Active, Completed (every drone flew its part and
    landed) or Aborted."""
    return client.mission(mission_id)


def plan_mission(
    client: SwarmClient,
    name: str,
    mission_type: str,
    waypoints: list[dict[str, float]],
    drone_count: int,
    spacing_meters: float = 2.0,
    formation: str | None = None,
) -> dict[str, Any]:
    """Propose a mission. Nothing flies: the answer is a plan with a preview — every
    drone's path, how long it takes, and any pair of drones that would come too close
    ("Conflicted": it cannot be approved; propose a different plan). A person must approve
    it; they are then given a single-use approval code, and only with that code can
    `dispatch_mission` fly it. `mission_type` is "waypoint" or "formation"; `formation` is
    "line" or "v"; waypoints are {x, y, z} in metres, world frame."""
    payload = build_mission_payload(
        name,
        mission_type,
        [Waypoint(float(w["x"]), float(w["y"]), float(w["z"])) for w in waypoints],
        drone_count,
        spacing_meters,
        formation,
    )
    return client.plan_mission(payload)


def get_mission_plan(client: SwarmClient, plan_id: str) -> dict[str, Any]:
    """A plan's status (PendingApproval, Conflicted, Approved, Rejected, Dispatched,
    Expired) and its preview. It never shows an approval code."""
    return client.mission_plan(plan_id)


def dispatch_mission(client: SwarmClient, plan_id: str, approval_code: str) -> dict[str, Any]:
    """Fly an approved plan. `approval_code` is the single-use code the person who
    approved the plan was given — ask them for it; it cannot be obtained any other way.
    Returns the mission now flying. A wrong code is refused (403); a plan that is not
    approved, already dispatched or expired is refused (409)."""
    return client.dispatch_plan(plan_id, approval_code)


def abort_mission(client: SwarmClient, mission_id: str, action: str = "rtl") -> dict[str, Any]:
    """Stop an active mission: "rtl" (every drone returns to its pad and lands, the
    default), "land" (land where it is) or "hold" (hover). Not gated: stopping never waits
    for approval."""
    if action not in ABORT_ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ABORT_ACTIONS)}, got {action!r}")
    return client.abort_mission(mission_id, action)


def land_all(client: SwarmClient) -> dict[str, Any]:
    """Emergency: every drone lands where it is, whatever it was doing, and the active
    mission ends. Not gated: stopping never waits for approval."""
    return client.land_all()


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "get_swarm_status",
        "Swarm status",
        "read",
        True,
        False,
        True,
        False,
        "GET /api/swarm/state",
        get_swarm_status,
    ),
    ToolSpec(
        "get_mission",
        "Mission status",
        "read",
        True,
        False,
        True,
        False,
        "GET /api/missions/{id}",
        get_mission,
    ),
    ToolSpec(
        "plan_mission",
        "Propose a mission plan",
        "plan",
        False,
        False,
        False,
        False,
        "POST /api/mission-plans",
        plan_mission,
    ),
    ToolSpec(
        "get_mission_plan",
        "Mission plan status",
        "read",
        True,
        False,
        True,
        False,
        "GET /api/mission-plans/{id}",
        get_mission_plan,
    ),
    ToolSpec(
        "dispatch_mission",
        "Fly an approved plan",
        "gated-write",
        False,
        True,
        True,
        True,
        "POST /api/mission-plans/{id}/dispatch",
        dispatch_mission,
    ),
    ToolSpec(
        "abort_mission",
        "Stop a mission",
        "safety-write",
        False,
        True,
        True,
        True,
        "POST /api/missions/{id}/abort",
        abort_mission,
    ),
    ToolSpec(
        "land_all",
        "Land every drone now",
        "safety-write",
        False,
        True,
        True,
        True,
        "POST /api/swarm/land",
        land_all,
    ),
)
