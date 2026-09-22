# Architecture

This repository is measured against the estate's constitution rather than restating it:
[`konradcinkusz/architecture-standards`](https://github.com/konradcinkusz/architecture-standards),
specifically
[`docs/architecture/00-REFERENCE-ARCHITECTURE.md`](https://github.com/konradcinkusz/architecture-standards/blob/main/docs/architecture/00-REFERENCE-ARCHITECTURE.md)
(principles P1–P15) and the operational guides it links to. `.claude/settings.json`
declares the marketplace and enables `architecture-core`, per
[`REPO-BASELINE.md` §7](https://github.com/konradcinkusz/architecture-standards/blob/main/docs/guides/REPO-BASELINE.md#7-standards-adoption-is-declared-not-remembered).

That constitution was extracted from .NET Aspire SaaS products deployed to Fly.io/Azure.
`swarmsim` is a robotics simulation platform whose heaviest layer (Gazebo + PX4 SITL +
ROS 2) is not a .NET Aspire resource at all, so applying the constitution here means
adapting it deliberately rather than forcing every principle to fit. What was kept,
what was adapted, and why, is recorded in:

- [`docs/architecture/DEVIATIONS.md`](DEVIATIONS.md) — the open-deviations register
  (constitution §3a): which principles this repo does not yet meet, and the accepted
  reasoning or the trigger that will close each one.
- [`docs/adr/`](https://github.com/konradcinkusz/swarmsim/tree/main/docs/adr) — the
  individual decision records, one per architectural choice, each citing the principle
  it follows or the one it knowingly departs from.

## What this repo is

A simulation and coordination platform for multi-drone ("swarm") missions, built on
existing open-source flight-simulation engines (Gazebo, PX4 SITL, ROS 2) rather than a
custom physics engine, with a .NET backend exposing mission definition and swarm-state
APIs as the integration point for a future natural-language mission layer. See the
[root README](https://github.com/konradcinkusz/swarmsim#readme) for the milestone plan
(M0–M4) and quickstart.

## Layering

```
SwarmApi.Api            → transport only: bind, validate, delegate (P9)
  SwarmApi.Application   → use-case services (MissionService: dispatch, state query)
    SwarmApi.Domain      → entities, value objects, pure trajectory/formation math
    SwarmApi.Infrastructure → ISwarmBridge: RosBridgeSwarmBridge (real) / SimulatedSwarmBridge (P8 fallback)
```

`swarm_coordination` (ROS 2) mirrors the same discipline on the Python side: ROS nodes
are thin I/O adapters (subscribe/publish only); the waypoint and formation math they call
lives in plain, `rclpy`-free modules that unit-test without a ROS 2 installation.

## Compliance checklist

The constitution's §3 checklist, item by item, for `SwarmApi.Api` (the one service this
repository runs). Every row is **Yes**, a **Deviation** with its row in
[`DEVIATIONS.md`](DEVIATIONS.md), or **N/A** with the reason — the last answer is the one
that has to earn itself. The Python side (`swarm_coordination`, `mcp_server`) follows the
same discipline where a rule has a meaning outside .NET: nodes and MCP tool registration
are thin adapters over pure, tested modules (P9/P10/P13 in spirit).

Last worked through: 2026-09-22.

| # | Checklist item | Answer | Evidence, or why not |
|---|---|---|---|
| 1 | Declared in the AppHost with `WithReference`, `WaitFor`, `WithHttpHealthCheck` | Deviation | No AppHost — P1 row; `docker/docker-compose.yml` gates `api` on the `sim` healthcheck instead |
| 2 | Calls `AddServiceDefaults()` and `MapDefaultEndpoints()` | Yes | `backend/src/SwarmApi.Api/Program.cs` |
| 3 | Exposes `/health` and `/alive`; the platform health check points at `/health` | Yes, partly N/A | Both endpoints exist and are tested (`HealthEndpointTests`); there is no platform (no `fly.toml`) to point at them — P7 rows |
| 4 | Emits OTLP traces, metrics and logs | Deviation | P15 row |
| 5 | Owns its database; no other service connects to it | N/A | Stateless — P3/P4 row |
| 6 | Schema applied by `MigrateAsync` from provider-specific migrations, in a hosted service | N/A | No entity model, no schema — P3/P4 row |
| 7 | All configuration from environment variables; no secret in source, config or comment; secret scanner in CI | Yes | Options bound from `RosBridge__*` / `Auth__*`; gitleaks scans full history in CI (`ci.yml`, job `secret-scan`) and before each commit (`scripts/hooks/pre-commit`, installed by `scripts/setup.sh`) |
| 8 | Exactly one service holds a signing key; all others validate against its JWKS | Yes | `authservice` signs (RS256); `SwarmApi.Api` only validates through JWKS discovery ([ADR-0005](../adr/0005-mcp-server-and-bearer-auth.md)) |
| 9 | Shared kernel holds no entity, DTO, enum, seed data or user-facing string — asserted by an architecture test and a CI size check | Yes, partly | `ArchitectureTests` + the kernel size step in `ci.yml`; JWT wiring and OpenAPI are not in the kernel — P2 row |
| 10 | Every optional integration has a working no-op or fallback | Yes | rosbridge → simulated swarm ([ADR-0003](../adr/0003-rosbridge-degrade-pattern.md)); `authservice` → Open mode ([ADR-0005](../adr/0005-mcp-server-and-bearer-auth.md)) |
| 11 | Health endpoint reports every optional integration's state; the startup banner prints the same | Deviation, after startup | Both report `swarmBridge` and `auth` at startup; a rosbridge drop afterwards is not reflected — P8 row |
| 12 | Multi-stage Dockerfile; runtime major = TFM major; listens on `:8080`; non-root | Yes | `docker/Dockerfile.api`: SDK 10 builds `net8.0`, runs on `aspnet:8.0`, `USER app` |
| 13 | One `fly.toml`; `min_machines_running = 1` if called in-request | Deviation | P7 `swarmsim-api` row (trigger fired) |
| 14 | Outbound `HttpClient`s carry the standard resilience handler with explicit timeouts | N/A | The API makes no outbound HTTP call; its one outbound connection is the rosbridge WebSocket, which has an explicit connect timeout (`RosBridge:ConnectTimeoutSeconds`) |
| 15 | `Program.cs` is a manifest; wiring in `ServiceCollectionExtensions` | Yes | `Program.cs` is capability calls; bridge and auth decisions live in `SwarmApi.Infrastructure/ServiceCollectionExtensions.cs` |
| 16 | Extension points are interfaces registered in DI, not base classes | Yes | `ISwarmBridge` (two implementations, no base class) |
| 17 | Has a test project; the logic-bearing layer is covered | Yes | `SwarmApi.Domain.Tests`, `SwarmApi.Application.Tests`, `SwarmApi.Api.Tests` (host-level, including Enforced auth) |
| 18 | Built by the tag-driven workflow with path-based change detection | Deviation | P12 row |
| 19 | Architectural decisions recorded in `docs/` | Yes | Seven ADRs in [`docs/adr/`](https://github.com/konradcinkusz/swarmsim/tree/main/docs/adr), amended in place (dated) when the code moves on |

The repository baseline (architecture-standards `REPO-BASELINE.md`) is met for CODEOWNERS,
grouped dependency updates, `.editorconfig`, central package management, PR/issue
templates, `.gitattributes`, exclusion-based `.dockerignore` files, pre-commit plus CI
secret scanning, one-command onboarding (`scripts/setup.sh`) and a committed
`docker/.env.example`.

Principles deferred with a recorded reason: see `DEVIATIONS.md`.
