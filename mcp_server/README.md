# mcp_server

An MCP (Model Context Protocol) server that lets an agent work with the swarm through
`SwarmApi.Api`'s REST surface — no ROS 2 bridge of its own, no dependency on
`swarm_coordination` ([ADR-0005](../docs/adr/0005-mcp-server-and-bearer-auth.md)). An agent can
read everything and stop anything, but it **cannot make drones fly without a person**: it
proposes a plan, a person approves it and is given a single-use approval code, and only
that code dispatches the plan ([ADR-0009](../docs/adr/0009-agent-write-gate.md)). The API
enforces the gate; this server just has no way around it.

## Tools

The classification and hints are normative — [`BEHAVIOUR.md`](BEHAVIOUR.md) holds the table
and the rules, and `test/test_behaviour.py` checks the code against it.

| Tool | What it does | Classification |
|---|---|---|
| `get_swarm_status` | Every drone's position, battery, armed state, mode; the active mission; whether the swarm is connected | read |
| `get_mission` | One mission's status (Active, Completed, Aborted) | read |
| `plan_mission` | Propose a mission; returns the plan with its preview — paths, duration, conflicts | plan |
| `get_mission_plan` | A plan's status and preview (never its approval code) | read |
| `dispatch_mission` | Fly an approved plan, with the approval code a person was given | gated-write |
| `abort_mission` | Stop a mission: return to launch (default), land, or hold | safety-write |
| `land_all` | Every drone lands where it is | safety-write |

Each tool publishes MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`), so a client can ask for confirmation before the destructive ones. There
is no tool that approves a plan and none that dispatches a mission without one; the old
`start_mission` tool, which did, is gone.

**How a mission gets flown from a conversation:** the agent calls `plan_mission` and
shows the preview. The person approves it in the dashboard (or with
`POST /api/mission-plans/{id}/approve`), which shows them the approval code once. They give
the code to the agent, which calls `dispatch_mission`. A plan whose paths bring two drones
closer than 2 m is `Conflicted` and cannot be approved at all.

**Failures say what is known.** Every write carries an `Idempotency-Key`; a write that gets
no answer is retried with the same key (the API replays its first answer, so nothing flies
twice) and, if it still gets none, is reported as possibly done — check the state before
trying again. A refused connection is reported as "nothing was sent"; an API error as its
status, title and detail.

## Configuration

| Env var | Default | Description |
|---|---|---|
| `SWARM_API_BASE_URL` | `http://localhost:5000` | Base URL of a running `SwarmApi.Api` |
| `SWARM_API_TOKEN` | *(unset)* | Bearer token, obtained by logging into `authservice` yourself — this server never logs in. Needed once `SwarmApi.Api` runs in Enforced mode, where it also means the agent cannot approve the plans it proposes |
| `SWARM_API_TIMEOUT_S` | `10` | Per-request timeout |

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

`swarm_client.py` and `tools.py` import nothing from `mcp`, so the tests need neither the
`mcp` package nor a running API: the client is exercised against a local HTTP stub
(refused connections, timeouts, retries under one key, error bodies), and every tool is
checked against `BEHAVIOUR.md` and against the API's own endpoint classification.
`server.py` only registers those functions with their annotations.
