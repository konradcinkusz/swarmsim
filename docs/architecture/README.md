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
  SwarmApi.Application   → use cases (MissionService: validate, dispatch, abort, land, lifecycle;
                           MissionPlanService: plan, preview, approve, dispatch with the code)
    SwarmApi.Domain      → entities, value objects, pure trajectory/formation math
    SwarmApi.Infrastructure → ISwarmBridge: RosBridgeSwarmBridge (real) / SimulatedSwarmBridge (P8 fallback)
```

`swarm_coordination` (ROS 2) mirrors the same discipline on the Python side: ROS nodes
are thin I/O adapters (subscribe/publish, call MAVROS services); every decision they act
on — OFFBOARD sequencing, frames, mission planning, swarm state — lives in plain,
`rclpy`-free modules that unit-test without a ROS 2 installation.

The two sides meet at one contract: `contracts/rosbridge/` holds a JSON Schema and an
example for each rosbridge message (`/swarm/mission`, `/swarm/command`, `/swarm/state`),
and both test suites are held to the same files (P11).

The scenario instrument ([ADR-0008](../adr/0008-scenario-instrument.md)) sits beside
them: YAML scenarios (`contracts/scenario/`) flown in a seeded kinematic simulation
against the swarm's own modules, through the same rosbridge contract, with a mutation
check that proves each scenario would notice a regression. It runs on every push and,
as the root `action.yml`, inside anyone's CI.

## Agents and the write gate

An agent reaches the swarm through `mcp_server/` — and only as far as
[ADR-0009](../adr/0009-agent-write-gate.md) lets it:

1. It proposes a plan, which is checked for conflicts before anything flies.
2. A person approves the plan and receives a single-use code.
3. The agent dispatches with that code.

The API enforces each step; the MCP server has no tool that approves, and no tool that
flies without the code. [API-SURFACE.md](API-SURFACE.md) classifies every endpoint and
[`mcp_server/BEHAVIOUR.md`](https://github.com/konradcinkusz/swarmsim/blob/main/mcp_server/BEHAVIOUR.md)
every tool; tests read both tables. Every write honours a client-supplied
`Idempotency-Key`, so a retry after a timeout replays the first answer instead of flying
twice.

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
| 3 | Exposes `/health` and `/alive`; the platform health check points at `/health` | Yes | Both endpoints exist and are tested (`HealthEndpointTests`); `flyio/swarmsim-api.fly.toml`'s check points at `/health`, and the deploy verifies what it cannot see (Enforced, File) — [ADR-0011](../adr/0011-hosted-api-and-run-store.md) |
| 4 | Emits OTLP traces, metrics and logs | Yes | `SwarmApi.ServiceDefaults/Telemetry.cs`: exported when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, `Off` (and reported) when not; the service's own spans and bounded-tag counters in `SwarmTelemetry` — [ADR-0010](../adr/0010-opentelemetry.md) |
| 5 | Owns its database; no other service connects to it | N/A | Stateless — P3/P4 row |
| 6 | Schema applied by `MigrateAsync` from provider-specific migrations, in a hosted service | N/A | No entity model, no schema — P3/P4 row |
| 7 | All configuration from environment variables; no secret in source, config or comment; secret scanner in CI | Yes | Options bound from `RosBridge__*` / `Auth__*`; gitleaks scans full history in CI (`ci.yml`, job `secret-scan`) and before each commit (`scripts/hooks/pre-commit`, installed by `scripts/setup.sh`) |
| 8 | Exactly one service holds a signing key; all others validate against its JWKS | Yes | `authservice` signs (RS256); `SwarmApi.Api` only validates through JWKS discovery ([ADR-0005](../adr/0005-mcp-server-and-bearer-auth.md)) |
| 9 | Shared kernel holds no entity, DTO, enum, seed data or user-facing string — asserted by an architecture test and a CI size check | Yes, partly | `ArchitectureTests` + the kernel size step in `ci.yml`; JWT wiring and OpenAPI are not in the kernel — P2 row |
| 10 | Every optional integration has a working no-op or fallback | Yes | rosbridge not configured → simulated swarm; configured but unreachable → `Disconnected`, writes answer 503 and the bridge keeps reconnecting — never a simulated swarm standing in for a real one ([ADR-0003](../adr/0003-rosbridge-degrade-pattern.md) and its amendments); `authservice` → Open mode ([ADR-0005](../adr/0005-mcp-server-and-bearer-auth.md)), unless `Auth:Required` says a deployment must not run Open; no OTLP endpoint → telemetry Off; no run directory → runs in memory ([ADR-0010](../adr/0010-opentelemetry.md), [ADR-0011](../adr/0011-hosted-api-and-run-store.md)) |
| 11 | Health endpoint reports every optional integration's state; the startup banner prints the same | Yes | `/health` reports `swarmBridge` as it is at that moment (Degraded while `Disconnected`), `lastStateAgeSeconds`, `auth`, `telemetry` and `scenarioRuns`; the startup log names each mode (`ServiceCollectionExtensions`, `Telemetry`) |
| 12 | Multi-stage Dockerfile; runtime major = TFM major; listens on `:8080`; non-root | Yes, with a note | `docker/Dockerfile.api`: SDK 10 builds `net8.0`, runs on `aspnet:8.0`. The process runs as `app`; the container starts as root only so `backend/docker-entrypoint.sh` can hand a mounted volume to `app` before dropping to it (Fly mounts volumes root-owned) — ADR-0011 |
| 13 | One `fly.toml`; `min_machines_running = 1` if called in-request | Yes, not deployed | `flyio/swarmsim-api.fly.toml`, `min_machines_running = 0` (nothing calls it in-request); not deployed yet — P7 `swarmsim-api` row |
| 14 | Outbound `HttpClient`s carry the standard resilience handler with explicit timeouts | N/A | The API makes no outbound HTTP call; its one outbound connection is the rosbridge WebSocket, which has an explicit connect timeout, a doubling reconnect back-off and a message size cap (`RosBridge:*`) |
| 15 | `Program.cs` is a manifest; wiring in `ServiceCollectionExtensions` | Yes | `Program.cs` is capability calls; bridge and auth decisions live in `SwarmApi.Infrastructure/ServiceCollectionExtensions.cs` |
| 16 | Extension points are interfaces registered in DI, not base classes | Yes | `ISwarmBridge` (two implementations, no base class) |
| 17 | Has a test project; the logic-bearing layer is covered | Yes | `SwarmApi.Domain.Tests` (including deconfliction), `SwarmApi.Application.Tests` (mission lifecycle, the plan and approval gate), `SwarmApi.Infrastructure.Tests` (the rosbridge protocol against `contracts/rosbridge/`, the bridge against an in-process rosbridge), `SwarmApi.Api.Tests` (host-level, including Enforced auth, idempotency, and every endpoint against [API-SURFACE.md](API-SURFACE.md)); the dashboard in a real browser (`e2e/`, Playwright, in CI) |
| 18 | Built by the tag-driven workflow with path-based change detection | Yes, not run | `.github/workflows/flyio.yml`: a `v*` tag → tests → change detection against the previous tag (missing app always selected) → build once → deploy → post-deploy check; never run against a real Fly org — P12 row |
| 19 | Architectural decisions recorded in `docs/` | Yes | Thirteen ADRs in [`docs/adr/`](https://github.com/konradcinkusz/swarmsim/tree/main/docs/adr), amended in place (dated) when the code moves on; the promotion test in [`docs/PROMOTION.md`](../PROMOTION.md) |

The repository baseline (architecture-standards `REPO-BASELINE.md`) is met for CODEOWNERS,
grouped dependency updates, `.editorconfig`, central package management, PR/issue
templates, `.gitattributes`, exclusion-based `.dockerignore` files, pre-commit plus CI
secret scanning, one-command onboarding (`scripts/setup.sh`) and a committed
`docker/.env.example`.

Principles deferred with a recorded reason: see `DEVIATIONS.md`.
