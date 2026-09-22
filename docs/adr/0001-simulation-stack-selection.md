# ADR-0001: Simulation stack — Gazebo Harmonic + PX4 SITL + ROS 2 Humble

## Status

Accepted

## Context

The business analysis ("Plan implementacji: platforma symulacji roju dronów") proposes
building the simulation foundation on existing open-source engines rather than a custom
flight-physics implementation: Gazebo (Harmonic/Ionic, not Classic) for 3D physics and
rendering, PX4 SITL as the autopilot, ROS 2 (Humble/Jazzy) as the multi-agent middleware.

This is not covered by `architecture-standards` at all — the constitution governs .NET
Aspire services, not robotics simulation engines — so there is nothing to adapt here;
the question is only whether the analysis's own reasoning holds up.

## Decision

Accept the analysis's stack choice as-is:

- **Gazebo Harmonic** (not Classic, which is in its deprecation window) — Apache 2.0,
  maintained by Open Robotics, native MAVLink bridge to PX4.
- **PX4 SITL**, pinned to a specific tagged release (v1.15.x) rather than `main`, to
  avoid the PX4/ROS 2 compatibility drift the analysis calls out as a risk.
- **ROS 2 Humble** (LTS, supported through 2027) over Jazzy — Humble is the version most
  third-party swarm references (XTDrone, Aerostack2) currently target, which matters
  more here than being on the newest LTS.

## Consequences

- The simulation container (`docker/Dockerfile.sim`) compiles PX4 from source, which is
  slow (documented in the root README as a "normal, not a bug" first-build cost) and is
  therefore never built in CI — see ADR-0004 for what CI validates instead.
- Pinning PX4/ROS 2/Gazebo versions together means a deliberate, recorded bump is
  required to move any of the three; drift between them is exactly the failure mode the
  analysis's own risk list names.

Worked example: `docker/Dockerfile.sim`, `docs/adr/0004-ci-scope-for-simulation-stack.md`.

## Amendment — 2026-09-22: the image did not match this decision

Until today the simulation image installed Gazebo through PX4's own
`Tools/setup/ubuntu.sh`, and at the pinned v1.15.0 that script installs **Garden** on
Ubuntu 22.04 — end of life since November 2024 — not the Harmonic chosen above. Nothing
noticed, because nothing built the image. `docker/Dockerfile.sim` now installs
`gz-harmonic` from packages.osrfoundation.org itself and runs PX4's installer with
`--no-sim-tools`; PX4 v1.15's `gz_bridge` looks for Harmonic's `gz-transport13` first,
and the build fails if `gz_bridge` was left out. The first consequence above is also
revised: the image is built in CI now, by the SITL smoke job — see ADR-0004's amendment.
The lesson generalises to the rest of this ADR: a pin is only a pin if something builds
against it.
