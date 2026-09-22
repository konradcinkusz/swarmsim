# ADR-0009: An agent flies drones only through a plan, a person and a single-use code

## Status

Accepted (2026-09-22). Replaces [ADR-0005](0005-mcp-server-and-bearer-auth.md)'s
`start_mission` tool; ADR-0005's auth decision stands.

## Context

ADR-0005 gave the MCP server a `start_mission` tool: `POST /api/missions` with the
operator's token. Read against the standards, that tool had four problems.

- **An agent could make drones fly with no person deciding.** The token proved *whose*
  authority the call used, not that anyone had looked at this mission. The only thing
  between a model and a take-off was the model's own judgement.
  architecture-standards AI-EVALS §8 names that exactly: "the agent's good behaviour is
  UX; the service boundary is security. An agent that can only be stopped by its own
  prompt is not human-in-the-loop."
- **Which calls were writes was implicit.** Nothing written down said which tools and
  endpoints change the world, so nothing could check it. AI-EVALS §4 asks for a normative
  per-tool table and warns against name prefixes, which classify every future write as a
  read.
- **A timed-out write had two bad outcomes.** A timed-out `POST /api/missions` may have
  launched a mission. Retrying could launch a second swarm on the same route; not
  retrying left the agent guessing. SERVICE-API-PATTERNS §5 ("A write that timed out is
  not a write that failed") names the only fix: a client-supplied idempotency key the
  service honours.
- **The server no longer imported.** It used `mcp.server.fastmcp`, which the MCP Python
  SDK 2.x removed. `mcp>=1.2.0` had no upper bound, so a fresh install got 2.x and failed
  on import.

The scenario study ([docs/research/scenario-study.md](../research/scenario-study.md)) adds
a domain reason to look before flying: a V formation launched from the pads puts two
drones 0.48 m apart three seconds after dispatch. The flight would have shown that; a
plan could have caught it first.

## Decision

**A mission from an agent is a plan. A person approves it. It flies only with the
single-use code that approval produced. The API enforces every step; the MCP server has no
way around it.**

- **Plans** (`POST /api/mission-plans`) take the same body as `POST /api/missions` and
  are validated against the same limits. Nothing flies. The answer is a preview:
  - every drone's path from where the swarm reports it (or its pad, when it has not
    reported);
  - how long the longest path takes;
  - the closest approach between any two drones;
  - the assumptions the preview rests on.

  Deconfliction flies every path at the swarm's cruise speed (2 m/s), all drones leaving
  together, samples every pair's distance and reports each pair that comes within 2 m. A
  plan with a conflict is **Conflicted** and cannot be approved: propose a different
  one. This checks the geometry, not the flight — real drones do not keep a common speed
  — and it catches the V-formation crossing.
- **Approval** (`POST /api/mission-plans/{id}/approve`) is a person's decision. It
  returns an **approval code** exactly once. The code is 192 bits from the OS CSPRNG, as
  base64url; the service keeps only its SHA-256 and compares a presented code in
  constant time. In Enforced auth mode, the identity that proposed a plan cannot approve
  it (403). A plan nobody decides on within 60 minutes expires. An approval not used
  within 10 minutes lapses. **Reject** works on a plan pending approval, conflicted, or
  approved but not yet dispatched.
- **Dispatch** (`POST /api/mission-plans/{id}/dispatch` with `approvalCode`) flies the
  approved mission once:
  - a wrong code is 403;
  - a plan that is not approved, already dispatched or expired is 409;
  - the code is consumed before the mission is sent, so two callers racing with one code
    cannot both fly;
  - if the swarm is unreachable (503), the code is given back so the same approval can be
    retried.
- **Stopping is never gated.** Abort and land-all need no approval: stopping must not wait
  for a person.
- **Every write honours `Idempotency-Key`.** Keys are scoped to the caller, method and
  path.
  - A replay returns the stored answer with `Idempotency-Replayed: true`.
  - The same key with a different body is 422; one still running is 409.
  - A 5xx is not stored, so a retry runs again.
  - Stored in memory for 24 h, at most 10 000 entries.
- **The classification is written down and tested.**
  [`docs/architecture/API-SURFACE.md`](../architecture/API-SURFACE.md) classifies every
  endpoint as read, plan, approval, gated-write, write or safety-write, with its
  Enforced-mode rule and whether it honours `Idempotency-Key`. `ApiSurfaceTests` fails on
  any endpoint that is missing from the table, or that disagrees with its row.
  [`mcp_server/BEHAVIOUR.md`](https://github.com/konradcinkusz/swarmsim/blob/main/mcp_server/BEHAVIOUR.md)
  does the same for the MCP tools. Each tool must have the class of the endpoint it
  calls, and seven deliberately broken tool sets must each fail a check (AI-EVALS §9).
- **The MCP server's tools:**

  | Class | Tools |
  |---|---|
  | read | `get_swarm_status`, `get_mission`, `get_mission_plan` |
  | plan | `plan_mission` |
  | gated-write | `dispatch_mission` (needs the code) |
  | safety-write | `abort_mission`, `land_all` |

  - Every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`,
    `idempotentHint`, `openWorldHint`), so a client can ask before the destructive ones.
  - There is no approve tool and no tool for `POST /api/missions`.
  - Its client tells three failures apart: an API answer (status and detail), a refused
    connection (nothing was sent), and no answer at all.
  - A write with no answer is retried under the same key, twice at most, then reported as
    "may have taken effect — check the state".
  - Built on MCP SDK 2.x (`MCPServer`), pinned `mcp>=2.2,<3`.
- **The dashboard is the person's side of the gate.** It lists open plans with their
  previews and has Approve and Reject buttons. After approval it shows the code once —
  a reload forgets it. It also has **Dispatch now**, plus abort and land-all.
  Playwright tests drive those flows in a real browser (`e2e/`).

## Consequences

- The gate holds against a misbehaving agent in both modes:
  - The code is needed to dispatch, and no tool approves.
  - An agent that bypasses the MCP server and calls the API directly still needs a
    person's code.
  - In Enforced mode it cannot approve its own plan either.
  - In Open mode, where nobody is identified, whoever can reach the API can approve.
    Open mode is for a simulator on one machine. This ADR makes it a rule: an API that
    anyone else can reach runs Enforced, so the hosted API ADR-0007 plans sets
    `Auth:Authority`.
- `POST /api/missions` stays: it is the operator's own dashboard button and the path for
  scripted clients and the SITL smoke. It is classified `write`, needs a token in
  Enforced mode, and no MCP tool calls it.
- The dashboard has no login, so in Enforced mode its buttons get 401s:
  - approve, reject and dispatch;
  - start;
  - abort and land.

  Approval then happens through the API with a token. The stop buttons failing in
  Enforced mode is the sharpest edge; it is recorded in the P5 row of
  [DEVIATIONS.md](../architecture/DEVIATIONS.md) together with the trigger that closes it.
- Plans and idempotency keys live in memory, like missions (the P3/P4 row). A restart
  forgets both, so an approval code does not survive one.
- The preview is only as good as its assumptions, so it states them. The same planning
  rules live in `mission_planning.py` (the swarm's assignment) and `MissionPlanner.cs`
  (the preview); nothing yet checks the two agree.

Worked example: `backend/src/SwarmApi.Application/MissionPlanService.cs`,
`backend/tests/SwarmApi.Api.Tests/MissionPlanEndpointTests.cs`,
`mcp_server/test/test_behaviour.py`, `e2e/test_dashboard.py`.
