"""The MCP server: registers the tools in tools.py, with the annotations and
classification mcp_server/BEHAVIOUR.md prescribes, over SwarmApi.Api's REST surface.
Why it wraps the REST API rather than ROS 2: docs/adr/0005. Why it cannot fly a mission
without a person's approval: docs/adr/0009.
"""

import functools
import inspect
import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from mcp_server.swarm_client import DEFAULT_TIMEOUT_S, SwarmClient, SwarmClientError
from mcp_server.tools import TOOLS, ToolSpec

INSTRUCTIONS = (
    "Tools for a drone swarm. To fly a mission: plan_mission, show the person the preview, "
    "and ask them to approve it — they receive a single-use approval code and give it to "
    "you; then dispatch_mission with that code. You cannot approve a plan yourself. "
    "abort_mission and land_all stop drones immediately and never need approval."
)

server = MCPServer("swarmsim", instructions=INSTRUCTIONS)


def _client() -> SwarmClient:
    return SwarmClient(
        os.environ.get("SWARM_API_BASE_URL", "http://localhost:5000"),
        os.environ.get("SWARM_API_TOKEN") or None,
        float(os.environ.get("SWARM_API_TIMEOUT_S", DEFAULT_TIMEOUT_S)),
    )


def _bind(spec: ToolSpec):
    """The tool as the model sees it: the spec's function minus its client argument."""
    signature = inspect.signature(spec.run)
    public = signature.replace(parameters=list(signature.parameters.values())[1:])

    @functools.wraps(spec.run)
    def tool(*args, **kwargs):
        bound = public.bind(*args, **kwargs)
        try:
            return spec.run(_client(), *bound.args, **bound.kwargs)
        except (SwarmClientError, ValueError) as error:
            raise ToolError(str(error)) from None

    tool.__signature__ = public
    tool.__annotations__ = {k: v for k, v in spec.run.__annotations__.items() if k != "client"}
    return tool


for _spec in TOOLS:
    server.tool(
        name=_spec.name,
        title=_spec.title,
        description=inspect.getdoc(_spec.run),
        annotations=ToolAnnotations(
            title=_spec.title,
            read_only_hint=_spec.read_only,
            destructive_hint=_spec.destructive,
            idempotent_hint=_spec.idempotent,
            open_world_hint=_spec.open_world,
        ),
    )(_bind(_spec))


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
