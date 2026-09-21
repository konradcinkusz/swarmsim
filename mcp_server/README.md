# swarmsim MCP server (proof of concept)

A minimal [MCP](https://modelcontextprotocol.io) server that exposes two of
`SwarmApi.Api`'s REST endpoints as MCP tools, for GitHub issue #20. It is a thin
wrapper: both tools take the same fields as their REST counterpart, call it over
HTTP, and return its JSON response unchanged. No mission/swarm business logic lives
here — that stays in `backend/src/SwarmApi.Application` and `SwarmApi.Domain`, per
this repo's `CLAUDE.md`.

This is a proof of concept, scoped out of CI per the issue — it is not wired into
`.github/workflows/ci.yml`.

## Tools

| Tool | Wraps | Arguments | Returns |
|---|---|---|---|
| `create_mission` | `POST /api/missions` | `name`, `mission_type` (`"waypoint"` \| `"formation"`, the request's `type` field), `waypoints` (list of `{x, y, z}` meters), `drone_count`, `spacing_meters` (default `2.0`) | The created `Mission` JSON (`id`, `name`, `type`, `waypoints`, `droneCount`, `spacingMeters`, `createdAtUtc`) on success; raises a tool error carrying SwarmApi.Api's status code and body if the request is rejected (e.g. its 400 validation-problem response) or the API is unreachable. |
| `get_swarm_state` | `GET /api/swarm/state` | none | The `SwarmState` JSON (`drones`, `activeMissionId`, `timestampUtc`, `bridgeMode`) exactly as SwarmApi.Api returns it. |

See the root [`README.md`](../README.md)'s Quickstart/Tutorial sections and
`backend/src/SwarmApi.Application/Contracts/CreateMissionRequest.cs` /
`backend/src/SwarmApi.Domain/{Mission,SwarmState}.cs` for the exact wire contracts
these mirror.

## Setup

```bash
cd mcp_server
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Requires Python 3.10+ (matches the `mcp` SDK's minimum).

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `SWARM_API_URL` | `http://localhost:5000` | Base URL of a running `SwarmApi.Api` instance. |
| `SWARM_API_TIMEOUT_SECONDS` | `10.0` | Per-request HTTP timeout. |

## Running it against a local `SwarmApi.Api`

1. Start the API (no simulation stack or Docker required — it falls back to a
   simulated swarm; see the root README's Quickstart):

   ```bash
   cd backend
   dotnet run --project src/SwarmApi.Api
   ```

   Note the port `dotnet run` prints (`http://localhost:5000` by default).

2. In another terminal, run this MCP server over stdio:

   ```bash
   cd mcp_server
   source .venv/bin/activate
   SWARM_API_URL=http://localhost:5000 python server.py
   ```

   It speaks MCP over stdio and is meant to be launched by an MCP client, not used
   interactively — you won't see anything print to the terminal once it's running.

3. Point an MCP client at it. For a client that reads a JSON config (e.g. Claude
   Desktop's `claude_desktop_config.json`):

   ```json
   {
     "mcpServers": {
       "swarmsim": {
         "command": "/absolute/path/to/mcp_server/.venv/bin/python",
         "args": ["/absolute/path/to/mcp_server/server.py"],
         "env": { "SWARM_API_URL": "http://localhost:5000" }
       }
     }
   }
   ```

   Any other MCP client that can spawn a stdio server works the same way — point its
   command at this venv's `python` and `server.py`, with `SWARM_API_URL` set.

## What's actually been verified

- `pip install -r requirements.txt` succeeds and pulls the official `mcp` SDK plus
  `httpx`.
- Both files pass `python -m py_compile`.
- The server was run for real: launched as an MCP stdio subprocess through the `mcp`
  SDK's own client (`mcp.client.stdio.stdio_client` + `ClientSession`), which listed
  both tools and called each one — against a small mock standing in for
  `SwarmApi.Api` (this sandbox has no reachable `.NET` SDK, per `CLAUDE.md`), since
  the shapes returned matched `Mission`/`SwarmState` exactly. `create_mission` was
  also exercised against a rejected (400) request to confirm SwarmApi.Api's
  validation-problem body surfaces as a tool error rather than being swallowed.
- It has **not** been run against a real `SwarmApi.Api` instance or a real MCP
  client (e.g. Claude Desktop) — do that per the steps above before relying on it.
