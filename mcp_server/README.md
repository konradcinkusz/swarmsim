# mcp_server

An MCP (Model Context Protocol) server exposing swarm-level tools over `SwarmApi.Api`'s
existing REST surface — no new ROS 2 bridge, no dependency on `swarm_coordination`. See
[`docs/adr/0005-mcp-server-and-bearer-auth.md`](../docs/adr/0005-mcp-server-and-bearer-auth.md)
for why it wraps the REST API rather than ROS 2/rosbridge directly, and why it stops at
two tools for now.

## Tools

| Tool | Maps to | Auth |
|---|---|---|
| `get_swarm_status` | `GET /api/swarm/state` | none — always open |
| `start_mission` | `POST /api/missions` | bearer token via `SWARM_API_TOKEN`, only required once `SwarmApi.Api` runs in Enforced mode |

`start_mission`'s `mission_type` accepts `"waypoint"` or `"formation"` — formation
offsets are computed server-side (`SwarmApi.Domain.Formation.Line`), so there is no
separate `define_formation` tool. Per-drone/subgroup task assignment
(`assign_swarm_task`) is not implemented here — see the ADR's "Open items this ADR does
not close".

## Configuration

| Env var | Default | Description |
|---|---|---|
| `SWARM_API_BASE_URL` | `http://localhost:5000` | Base URL of a running `SwarmApi.Api` |
| `SWARM_API_TOKEN` | *(unset)* | Bearer token, obtained by logging into `authservice` yourself — this server does not implement a login flow. Only needed once `SwarmApi.Api`'s `Auth:Authority` is configured (Enforced mode) |

## Run

```bash
cd mcp_server
pip install -e .
python -m mcp_server.server
```

Point an MCP client (Claude Code, Claude Desktop, ...) at it over stdio, e.g. in Claude
Code's MCP config:

```json
{
  "mcpServers": {
    "swarmsim": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "env": {
        "SWARM_API_BASE_URL": "http://localhost:5000",
        "SWARM_API_TOKEN": ""
      }
    }
  }
}
```

## Testing

```bash
cd mcp_server
pip install ruff pytest
ruff check .
pytest -v
```

Only `swarm_client.py` (pure request-building) is unit tested, the same way
`swarm_coordination` tests its pure logic and not its ROS node adapters —
`server.py`'s MCP tool registration needs the `mcp` package installed and a running
`SwarmApi.Api` to exercise meaningfully, and is covered by manual verification instead.
