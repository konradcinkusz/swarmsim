# API surface and write classification

Every endpoint `SwarmApi.Api` serves, and what kind of operation it is. **This table is
normative**: `backend/tests/SwarmApi.Api.Tests/ApiSurfaceTests.cs` reads it and fails if an
endpoint exists that is not listed here, if a listed one is gone, or if an endpoint's
authorization or idempotency does not match its row. A new endpoint is classified by adding
its row — never by its name (architecture-standards AI-EVALS §4: a naming convention
silently classifies every future write as a read).

| Method | Route | Class | Enforced mode | Idempotency-Key |
|---|---|---|---|---|
| ANY | `/health` | read | open | — |
| ANY | `/alive` | read | open | — |
| GET | `/api/swarm/state` | read | open | — |
| POST | `/api/swarm/land` | safety-write | token | honoured |
| POST | `/api/missions` | write | token | honoured |
| GET | `/api/missions/{id:guid}` | read | open | — |
| POST | `/api/missions/{id:guid}/abort` | safety-write | token | honoured |
| POST | `/api/mission-plans` | plan | token | honoured |
| GET | `/api/mission-plans` | read | open | — |
| GET | `/api/mission-plans/{id:guid}` | read | open | — |
| POST | `/api/mission-plans/{id:guid}/approve` | approval | token | honoured |
| POST | `/api/mission-plans/{id:guid}/reject` | approval | token | honoured |
| POST | `/api/mission-plans/{id:guid}/dispatch` | gated-write | token | honoured |
| POST | `/api/scenario-runs` | record | token | honoured |
| GET | `/api/scenario-runs` | private-read | token | — |
| GET | `/api/scenario-runs/{id:guid}` | private-read | token | — |
| GET | `/api/scenario-runs/compare` | private-read | token | — |

The classes:

- **read** — changes nothing. Open in both auth modes (docs/adr/0005).
- **private-read** — changes nothing, but returns someone's own data (their stored
  scenario runs), so Enforced mode asks for a token (docs/adr/0011).
- **record** — stores data; nothing flies (a scenario run's report).
- **plan** — records a proposal and its preview; nothing flies.
- **approval** — a person's decision on a plan. In Enforced mode the approver must not be
  the identity that proposed the plan.
- **gated-write** — makes drones fly, and only with the single-use code an approval produced
  (docs/adr/0009). This is the only way the MCP server can start a mission.
- **write** — makes drones fly with no approval step: the operator's own dashboard button
  and scripted clients. The MCP server has no tool for it.
- **safety-write** — stops or lands drones. Never gated: stopping must not wait on a person.

Every POST honours `Idempotency-Key`: a replay of the same request returns the original
answer (`Idempotency-Replayed: true`) instead of running again, the same key with a
different request is 422, and a 5xx is not stored, so a retry runs again.
