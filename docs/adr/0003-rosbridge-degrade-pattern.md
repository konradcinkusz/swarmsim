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

## Amendment — 2026-09-22: the names in this record, and what it did not cover

The decision above names types that were renamed before the code shipped:
`ISwarmStateProvider` / `IMissionDispatcher` became one interface, `ISwarmBridge`
(`backend/src/SwarmApi.Application/ISwarmBridge.cs`), and the two implementations are
`RosBridgeSwarmBridge` and `SimulatedSwarmBridge` (`backend/src/SwarmApi.Infrastructure/`).
`AdvanceTowardWaypoint` is `Trajectory.StepTowards` (`SwarmApi.Domain`). The decision itself
is unchanged; only the vocabulary in the text above is stale, and it is left as written so
the record shows what was decided at the time.

Two gaps the decision did not address are recorded here rather than silently absorbed:

- **Degradation is visible only at startup.** The bridge is chosen once; if the rosbridge
  connection drops afterwards there is no reconnection, and `GET /health` keeps reporting
  `Connected` while the swarm state silently goes stale. Tracked in
  `docs/architecture/DEVIATIONS.md` (P8 row) until the bridge reconnects and reports its
  live state.
- **The compose stack raced this decision.** `api` used to start as soon as the `sim`
  container existed, well before rosbridge listened, so the one-time probe almost always
  chose Simulated. `docker/docker-compose.yml` now gates `api` on the `sim` healthcheck
  (rosbridge accepting connections).

## Amendment — 2026-09-22 (later the same day): the decision itself, revised

The original decision — probe once at startup, fall back to the simulated swarm if the
probe fails — is replaced, because both of its failure modes were worse than the
degradation it was avoiding:

- **A configured swarm is never replaced by a simulated one.** If `RosBridge:Url` is set,
  the real bridge is registered, full stop. While rosbridge is unreachable it reports
  `Disconnected` (a new `SwarmBridgeMode`), refuses to dispatch (HTTP 503, so no caller
  mistakes a mission for flying), and reconnects in the background with a doubling
  back-off. The simulated swarm is reserved for "no URL configured" — the
  `git clone && dotnet run` case P8 names. A URL that is set but is not `ws://` or
  `wss://` stops startup rather than falling back, for the same reason. Showing an operator stand-in drones because
  the real ones were briefly unreachable at boot was the more dangerous degradation.
- **Degradation is visible for the process's whole life, not only at startup.**
  `/health` reports `swarmBridge` as Connected/Disconnected at the moment it is read,
  with `lastStateAgeSeconds`, and is `Degraded` (still HTTP 200) while disconnected. The
  swarm state is stamped with the live mode, so the dashboard says "disconnected —
  positions are stale" instead of showing old positions as live.
- **The connection's lifecycle belongs to the host** (`RosBridgeConnectionService`, a
  `BackgroundService`), not to a probe in `Program.cs`. One malformed or oversized message
  is counted and dropped; it no longer ends the receive loop.
- **Nothing the swarm did not report is invented.** Battery, armed state and flight mode
  come from MAVROS through `/swarm/state` or are null; the old parser stamped every drone
  `InFlight` at 100 % battery.

The messages crossing rosbridge are now written down once, in `contracts/rosbridge/`, and
both sides are tested against the same example files. Worked example:
`backend/tests/SwarmApi.Infrastructure.Tests/` (an in-process fake rosbridge that drops,
refuses and reconnects).
