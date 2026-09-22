# CLAUDE.md

Guidance for an AI agent (or a human) working in this repository.

## What this repo is

A drone-swarm simulation platform: Gazebo + PX4 SITL + ROS 2 for the simulation and
flight layer, a .NET backend (`backend/`) exposing mission and swarm-state REST APIs.
See the root [`README.md`](README.md) for the milestone plan and quickstart, and
[`docs/architecture/README.md`](docs/architecture/README.md) for the architecture and
which standards this repo follows.

## Standards

This repo is measured against
[`konradcinkusz/architecture-standards`](https://github.com/konradcinkusz/architecture-standards)
(declared in `.claude/settings.json`). Read the standard before re-deriving an
architectural rule from whatever code you happen to see — that is the single most
expensive failure mode the standards repo's own `AGENTS.md` names. Where this repo
deviates, the deviation is recorded in `docs/architecture/DEVIATIONS.md` with its
reasoning; check there before assuming a gap is accidental.

## Layout

| Path | What it is | Tooling |
|---|---|---|
| `docker/` | Composition root for the simulation stack (Gazebo/PX4/ROS 2), GUI override, entrypoint + its stub test | `docker compose`, `shellcheck` |
| `simulation/` | Gazebo worlds (file name = world name), PX4 per-drone configs (committed, not secrets) | — |
| `swarm_coordination/` | ROS 2 ament_python package: waypoint/formation logic + node wrappers | `colcon`, `pytest`, `ruff` |
| `backend/` | .NET solution: `SwarmApi.Domain/Application/Infrastructure/ServiceDefaults/Api` | `dotnet` |
| `mcp_server/` | MCP server: swarm-level tools over `SwarmApi.Api`'s REST surface, no ROS dependency | `pytest`, `ruff` |
| `docs/adr/` | One decision record per architectural choice | — |
| `docs/architecture/` | This repo's compliance checklist and deviation register | — |
| `scripts/` | `setup.sh` (onboarding + pre-commit hook), `scan-secrets.sh` (CI secret scan, locally) | `bash`, `gitleaks` |

## Before changing code

- Changing `swarm_coordination`: keep ROS-node files (`nodes/`) as thin I/O adapters;
  put logic in the plain, `rclpy`-free modules (`formation.py`, `waypoints.py`,
  `trajectory.py`) so it stays testable without a ROS 2 install. `pytest` in CI only
  imports the latter.
- Changing `backend/`: `Program.cs` stays a manifest (one call per capability); business
  logic goes in `SwarmApi.Application`/`SwarmApi.Domain`, not in the endpoint handlers.
  A new integration (a second bridge transport, a persistence store) is an interface in
  `SwarmApi.Application` plus a DI registration, not a base class.
- Changing `docker/Dockerfile.sim` or `docker/entrypoint.sh`: the image is not built in CI
  (see `docs/adr/0004-ci-scope-for-simulation-stack.md`), so read PX4's own init scripts
  for the pinned `PX4_VERSION` before assuming how a variable or make target behaves —
  `gz_x500` is a run target, not a build target, and PX4 treats any non-empty `HEADLESS`
  as headless. `docker/tests/test_entrypoint.sh` checks the entrypoint's decisions
  against stubs; keep it passing and extend it with the entrypoint.
- Adding to `.gitignore`: name the files, not an extension. `*.env` once hid the
  committed drone configs in `simulation/px4-configs/`.
- Any new external dependency (a second bridge transport, a cloud API) needs a working
  fallback per P8, following the pattern in
  `docs/adr/0003-rosbridge-degrade-pattern.md`. `SwarmApi.Api`'s bearer auth against
  `authservice` follows the same shape (Open/Enforced) — see
  `docs/adr/0005-mcp-server-and-bearer-auth.md`.
- Changing `mcp_server/`: keep `server.py` (MCP tool registration, needs the `mcp`
  package) thin; request-building and payload shaping belong in `swarm_client.py`, which
  stays free of the `mcp` import so `pytest` can exercise it with no network and no `mcp`
  install — mirrors the `swarm_coordination` node/pure-logic split.

## Local verification

- `.NET`: `dotnet test backend/SwarmPlatform.sln`. On an Ubuntu 24.04 sandbox whose
  network policy blocks Microsoft's download hosts, `apt-get install dotnet-sdk-8.0`
  (Ubuntu's own archive) usually still works; otherwise let CI run it.
- Python: `cd swarm_coordination && ruff check . && pytest`.
- MCP server: `cd mcp_server && ruff check . && pytest` (no `mcp` install needed — only
  `swarm_client.py` is exercised).
- Simulation config: `docker compose -f docker/docker-compose.yml config -q` (and
  `--profile auth config -q` for the optional `authservice` services;
  `DISPLAY=:0 ... -f docker/docker-compose.gui.yml config -q` for the GUI override).
- Shell: `shellcheck docker/entrypoint.sh scripts/*.sh && bash docker/tests/test_entrypoint.sh`.

Do not attempt to build `Dockerfile.sim` or run Gazebo/PX4 SITL inside an agent sandbox:
the build takes tens of minutes and the sandbox's network policy blocks hosts it needs.
The headless stack needs no GPU, though — only the optional GUI does — so a GitHub
Actions runner is a different question from this sandbox; see `docs/adr/0004`.
