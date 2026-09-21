# ADR 0005 — MCP server and bearer auth via `authservice`

**Status:** Accepted
**Date:** 2026-09-21

## Context

An Agent (an MCP client — Claude or another) becoming a direct consumer of `SwarmApi.Api`
was discussed as a differentiator over existing single-robot ROS↔MCP bridges: this repo
already has a domain layer above ROS 2 (`Mission`, `SwarmState`, `Formation`), so wrapping
*that* in MCP is swarm-level by construction, not per-drone, and needs no new bridge —
`ISwarmBridge` already exists.

That consumer is exactly the trigger [`docs/architecture/DEVIATIONS.md`](../architecture/DEVIATIONS.md)
already recorded for P5: "no authentication... Trigger: the first deployment reachable
outside localhost, or the LLM layer (M5) introducing a caller identity worth
distinguishing." An MCP server calling `POST /api/missions` on the swarm's behalf is that
caller identity. Shipping the MCP server without closing P5 at the same time would be
building the trigger and ignoring it.

[`konradcinkusz/authservice`](https://github.com/konradcinkusz/authservice) was evaluated
against a general-purpose IdP (Keycloak, Ory, etc.) and against P5's own requirement (JWT,
asymmetric signing). It fits `swarmsim`'s scope deliberately: MIT, RS256 with published
JWKS and rolling key rotation, a documented "own instance per consumer" deployment model,
and — per its own `docs/decisions/0003-scope.md` — an explicit refusal to become an OIDC
provider (SSO/SAML/LDAP federation, third-party client consent flows), which is exactly
the ceiling `swarmsim` does not need yet. Its `docs/decisions/0004-agent-to-agent-authorization.md`
is the closer analogue to this MCP scenario (a non-human caller acting with scoped,
short-lived authority), but its status there is **Proposed**, not implemented — nothing in
that service's code (`AgentIdentity`, `principal_type`, `/api/v1/agents/token`) exists yet.
This ADR does not depend on it: `swarmsim`'s MCP server is a proxy for a human-obtained
token, not an autonomous agent principal, so ordinary user-issued JWTs from `authservice`
are sufficient for this phase.

## Decision

1. **`mcp_server/`** — a new, minimal Python package, independent of `swarm_coordination`
   (no ROS dependency), exposing two MCP tools that wrap the *existing* REST surface
   rather than a new bridge:
   - `get_swarm_status` → `GET /api/swarm/state` (unauthenticated, matches point 3 below).
   - `start_mission` → `POST /api/missions`, forwarding a bearer token the operator
     obtained from `authservice` themselves (login flow, or a seeded account) — the MCP
     server does not implement a login flow of its own. It is a transparent proxy for a
     human-authorized caller, not yet an autonomous principal.

   `define_formation` is **not** a separate tool: `POST /api/missions` with
   `type: "formation"` already computes leader-follower offsets
   (`SwarmApi.Domain.Formation.Line`) — `start_mission` covers it. `assign_swarm_task`
   (per-drone/subgroup task assignment, as opposed to one mission for the whole swarm) is
   explicitly **out of scope here** — it needs new domain logic in `SwarmApi.Application`,
   not just a new MCP tool over what exists, and is follow-up work.

2. **`SwarmApi.Api` gains JWT bearer authentication against an external `authservice`
   instance (RS256, JWKS discovery)**, following the same degrade shape as
   [ADR-0003](0003-rosbridge-degrade-pattern.md)'s `ISwarmBridge`: `Auth:Authority` unset
   (the default — `dotnet run` with zero config, exactly as today) runs in **Open** mode,
   every endpoint reachable with no token. `Auth:Authority` configured runs in **Enforced**
   mode. Which mode is active is reported by `GET /health` (`auth: "Open" | "Enforced"`),
   mirroring `swarmBridge: "Connected" | "Simulated"`.

3. **Only `POST /api/missions` is gated when Enforced.** `GET /api/swarm/state`,
   `GET /api/missions/{id}`, and the dashboard (`wwwroot/`) stay unauthenticated. The
   dashboard's "Start demo mission" button (`app.js`) calls `POST /api/missions` with no
   token and has no login UI — gating that route too would silently break M4's manual
   acceptance criterion. The narrower scope is deliberate: the one thing this ADR is
   actually closing is "an Agent can dispatch a mission with a distinguishable identity",
   which is a write, not a read. Protecting the read endpoints and giving the dashboard a
   login flow is follow-up work, tracked as an open item below, not silently declared done.

## Consequences

### The "zero third-party NuGet packages" invariant gets one deliberate exception

`Directory.Packages.props` and the root README both state runtime code ships zero
third-party packages, relying only on `Microsoft.AspNetCore.App`'s `FrameworkReference`.
JWT bearer validation is **not** in that shared framework — unlike, say, health checks or
`System.Net.WebSockets.ClientWebSocket` — `Microsoft.AspNetCore.Authentication.JwtBearer`
and its `Microsoft.IdentityModel.*` dependencies are out-of-band NuGet packages requiring
an explicit `PackageReference`. Hand-rolling RS256/JWKS validation with only BCL crypto
was considered and rejected: JWT validation (audience/issuer/expiry checks, algorithm
confusion attacks, JWKS `kid` rotation) is a well-known place to introduce a subtle
security bug, and `authservice` itself makes the same call (its own ADR-0003: "do not
re-invent auth primitives"). One package, `Microsoft.AspNetCore.Authentication.JwtBearer`
(Microsoft-owned, matches this repo's own TFM), is added as the one recorded exception —
correctness over the badge.

### Open items this ADR does not close

- `assign_swarm_task` (per-drone task assignment) — new `SwarmApi.Application` logic,
  separate PR.
- `GET` endpoints and the dashboard remain unauthenticated even in Enforced mode — the
  dashboard has no login flow. `docs/architecture/DEVIATIONS.md`'s P5 row is narrowed, not
  deleted, to reflect exactly this partial scope.
- The MCP server holds a static, operator-supplied token (`SWARM_API_TOKEN`); it does not
  refresh it or implement `authservice`'s login flow itself. Fine for a single operator;
  worth revisiting once `authservice`'s ADR-0004 (agent-to-agent authorization) ships and
  gives non-human callers their own short-lived, audience-scoped credential instead of a
  borrowed human token.
- No published `ghcr.io/konradcinkusz/authservice` image tag exists yet (no `v*` release
  has been tagged in that repo at the time of this ADR) — `docker/docker-compose.yml`
  builds it from that repo's git context as an interim measure; swap to a pinned tag once
  a release exists (see that repo's README, "Releasing").
