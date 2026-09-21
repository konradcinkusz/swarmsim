# ADR-0004: What CI validates for the simulation stack, and what stays manual

## Status

Accepted

## Context

REPO-BASELINE.md: "CI runs the linters and tests the repo claims" — a committed but
never-executed check is worse than an honestly absent one (TESTING-STRATEGY.md §9, the
"test configs rot" rule). `docker/Dockerfile.sim` compiles PX4 from source against
Gazebo Harmonic and ROS 2 Humble; a full build is documented in the source analysis as
taking "kilkanaście-kilkadziesiąt minut" (tens of minutes) even with a warm cache, needs
a GPU for the GUI acceptance criterion, and this session's own sandbox cannot reach
several of the hosts that build would need (verified directly: the .NET SDK CDN alone was
already denied by this session's egress policy, and PX4/ROS/Gazebo's upstream hosts are
not on any allowlist either). Claiming a CI job runs that build without ever having run
it once would be exactly the pattern TESTING-STRATEGY.md §9 warns against.

## Decision

CI validates everything about the simulation layer that is mechanically checkable
without executing the heavy build:

- `hadolint` against both Dockerfiles (best-practice lint: layer ordering, pinned base
  images, no unnecessary `apt` cache left behind).
- `docker compose -f docker/docker-compose.yml config` — validates YAML syntax,
  interpolation, and service graph without building or pulling any image.
- The `simulation/worlds/*.sdf` and PX4 config files are checked for well-formedness
  (`xmllint` for SDF/XML).

It deliberately does **not**: build `Dockerfile.sim`, run PX4 SITL, or launch Gazebo.
M0's actual acceptance criterion (`docker-compose up` produces a drone that responds to
`commander takeoff`) is verified manually, on a GPU-capable machine, per the root
README's "Manual verification" section — and is recorded as a manual step, not silently
assumed covered by CI.

## Consequences

- A change to `Dockerfile.sim` that breaks the PX4 build (e.g., an incompatible apt
  package pin) will pass CI and only surface on the next manual run. This is an accepted
  gap, not an oversight: closing it costs a GPU-capable, long-running CI runner this
  project does not have access to yet.
- **Recorded trigger to close the gap:** once the project has a self-hosted runner (or a
  cloud runner) with GPU access and a build-time budget it can spend, add a scheduled
  (not per-PR) workflow that builds `Dockerfile.sim` headless and asserts `commander
  takeoff` succeeds against the spawned PX4 instance — the M0 acceptance criterion,
  automated. Until then, `docs/adr/0004` is the answer to "why doesn't CI catch this."

Worked example: `.github/workflows/ci.yml` (jobs `docker-lint`, `simulation-config`).
