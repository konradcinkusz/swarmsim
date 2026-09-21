# ADR-0003: The rosbridge connection is an optional dependency that degrades (P8)

## Status

Accepted

## Context

M3's acceptance criterion is that `POST /missions` produces real swarm movement and
`GET /swarm/state` returns current positions with sub-second latency. Proving that end
to end requires a running Gazebo + PX4 SITL + ROS 2 + rosbridge stack, which needs a
GPU-capable machine (or headless mode) and is exactly the piece this sandbox/CI cannot
run (ADR-0004). Building `SwarmApi.Api` so it can *only* be exercised against a live
simulation would mean the M3 acceptance criteria are untestable anywhere except a
developer's own machine — the opposite of P13.

Constitution P8 already states the general pattern for exactly this situation: "every
optional dependency degrades; it does not fail startup," with the test "`git clone &&
dotnet run` with zero cloud credentials must produce a working system with reduced
features."

## Decision

`ISwarmStateProvider` / `IMissionDispatcher` (P10: interface + DI, no base class) has two
implementations:

- **`RosBridgeSwarmStateProvider`** — connects to `RosBridge:Url` over a WebSocket
  (rosbridge_suite's JSON protocol), normalizing its topic/message dialect into the
  internal `SwarmState` model once, at this boundary (P11).
- **`SimulatedSwarmStateProvider`** — a deterministic in-memory swarm engine: on
  `POST /missions` it spawns the requested drone count and advances each drone toward its
  waypoints by elapsed time on every read, with no external process required.

Registration tries the rosbridge connection at startup with a short timeout; on failure
(or when `RosBridge:Url` is unset) it registers the simulated provider instead and logs
which mode is active — the same visible-degradation pattern P8 asks for (the worked
example: CopilotScope's `/api/health` naming its degraded integrations). `GET /health`
here reports `"swarmBridge": "Connected" | "Simulated"` for the same reason.

## Consequences

- The full mission lifecycle (`POST /missions` → `GET /swarm/state` → waypoints advance
  → mission completes) is unit- and integration-testable in CI against the simulated
  provider with no container, no GPU, and no flakiness budget spent on infrastructure —
  this is what actually makes M3's acceptance criteria checkable in this repository's CI.
- The simulated engine's movement math (`AdvanceTowardWaypoint`) is deliberately the same
  shape as the "real" trajectory the ROS 2 side computes
  (`swarm_coordination/trajectory.py`), so a reviewer comparing the two is comparing two
  independent, intentional implementations of one idea — not one canonical implementation
  and one stub that happens to look plausible.
- Risk accepted: the simulated provider is not a substitute for verifying the real
  rosbridge integration against a running Gazebo/PX4 stack. That verification is
  necessarily manual, on a GPU-capable machine, per the root README's M0/M3 manual
  verification steps — recorded, not silently assumed away.

Worked example: `backend/src/SwarmApi.Infrastructure/`, `backend/tests/SwarmApi.Api.Tests/`.
