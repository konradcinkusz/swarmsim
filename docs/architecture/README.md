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
- [`docs/adr/`](../adr/) — the individual decision records, one per architectural
  choice, each citing the principle it follows or the one it knowingly departs from.

## What this repo is

A simulation and coordination platform for multi-drone ("swarm") missions, built on
existing open-source flight-simulation engines (Gazebo, PX4 SITL, ROS 2) rather than a
custom physics engine, with a .NET backend exposing mission definition and swarm-state
APIs as the integration point for a future natural-language mission layer. See the
[root README](../../README.md) for the milestone plan (M0–M4) and quickstart.

## Layering

```
SwarmApi.Api            → transport only: bind, validate, delegate (P9)
  SwarmApi.Application   → use-case services (mission dispatch, state query)
    SwarmApi.Domain      → entities, value objects, pure trajectory/formation math
    SwarmApi.Infrastructure → IRosBridgeClient (real) / SimulatedSwarmStateProvider (P8 fallback)
```

`swarm_coordination` (ROS 2) mirrors the same discipline on the Python side: ROS nodes
are thin I/O adapters (subscribe/publish only); the waypoint and formation math they call
lives in plain, `rclpy`-free modules that unit-test without a ROS 2 installation.

## Compliance checklist

Principles applied as written: P6 (multi-stage Dockerfile for the API), P8 (every
optional dependency — the rosbridge connection — degrades to a working in-memory
fallback rather than failing startup), P9 (`Program.cs` as a manifest), P10 (interface +
DI, no base classes — `ISwarmStateProvider`, `IMissionDispatcher`), P11 (anti-corruption
at the edge — the rosbridge JSON dialect is normalized once, at `SwarmApi.Infrastructure`),
P13 (tests at the layer with the logic), P14 (this document and the ADRs), REPO-BASELINE
(hygiene files, secret scanning, dependency automation, CODEOWNERS).

Principles deferred with a recorded reason: see `DEVIATIONS.md`.
