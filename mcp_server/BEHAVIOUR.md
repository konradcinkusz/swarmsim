# MCP server behaviour

What an agent connected to this server can and cannot do to the swarm. **The table and the
rules below are normative**: `test/test_behaviour.py` checks every tool in
`mcp_server/tools.py` against this table, and each rule names the test that holds it. A
tool is write-classified because this table says so — not because of its name
(architecture-standards AI-EVALS §4).

| Tool | Classification | readOnly | destructive | idempotent | openWorld | Calls |
|---|---|---|---|---|---|---|
| `get_swarm_status` | read | yes | no | yes | no | `GET /api/swarm/state` |
| `get_mission` | read | yes | no | yes | no | `GET /api/missions/{id}` |
| `get_mission_plan` | read | yes | no | yes | no | `GET /api/mission-plans/{id}` |
| `plan_mission` | plan | no | no | no | no | `POST /api/mission-plans` |
| `dispatch_mission` | gated-write | no | yes | yes | yes | `POST /api/mission-plans/{id}/dispatch` |
| `abort_mission` | safety-write | no | yes | yes | yes | `POST /api/missions/{id}/abort` |
| `land_all` | safety-write | no | yes | yes | yes | `POST /api/swarm/land` |

The classifications are the API's own (`docs/architecture/API-SURFACE.md`); each tool's
class must match the class of the endpoint it calls. The four hints are the MCP tool
annotations the server publishes, so a client can ask for confirmation before the
destructive ones.

## Rules

1. **No tool can approve a plan, and no tool can dispatch a mission directly.** The only
   tool that makes drones fly is `dispatch_mission`, and it takes the single-use approval
   code a person was given when they approved the plan (docs/adr/0009). Held by
   `test_no_tool_can_approve_or_fly_without_the_gate`.
2. **Stopping is never gated.** `abort_mission` and `land_all` need no approval. Held by
   `test_stopping_needs_no_approval`.
3. **Every write carries an `Idempotency-Key`, and one without an answer is retried with the
   same key — twice at most — then reported as possibly done.** The API replays its first
   answer to a repeated key, so the retry cannot fly anything twice; after the last
   attempt the agent is told to check the state before trying again. Held by
   `test_a_write_without_an_answer_is_retried_under_the_same_key_then_reported_unknown`.
4. **Failures say what is known.** A refused connection is reported as "nothing was
   sent"; an API error as its status, title and detail; neither is retried. Held by
   `test_a_refused_connection_says_nothing_was_sent_and_is_not_retried` and
   `test_an_api_error_is_reported_with_its_status_and_detail`.
5. **The server never logs in.** It sends `SWARM_API_TOKEN` when one is configured and no
   `Authorization` header otherwise. Held by `test_the_operators_token_is_sent_only_when_set`.
6. **Ids are ids.** A plan or mission id that is not a UUID is refused before any request is
   made. Held by `test_ids_that_are_not_uuids_never_reach_a_url`.

The checks are shown to fail, not only to pass (architecture-standards AI-EVALS §9):
`test_a_broken_tool_set_is_caught` builds seven broken tool sets — a tool that approves, the
old ungated `start_mission` (plain and disguised as a read), a dispatch without the code, a
stop that waits for approval, `land_all` no longer destructive, a write classified as a read
— and each must fail a check on an assertion.

The gate is enforced by SwarmApi.Api, not by this server: an agent that ignored these tools
and called the API directly would still need a person's approval code to dispatch, and in
Enforced auth mode could not approve a plan it proposed (`MissionPlanServiceTests`,
`MissionPlanEndpointTests`).
