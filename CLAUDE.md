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
| `docker/` | Composition root for the simulation stack (Gazebo/PX4/ROS 2), GUI override, entrypoint + its stub test, SITL smoke test (`tests/sitl_smoke.py`) | `docker compose`, `shellcheck` |
| `simulation/` | Gazebo worlds (file name = world name), PX4 per-drone configs (committed, not secrets) | — |
| `swarm_coordination/` | ROS 2 ament_python package: per-drone controller, mission dispatcher, state aggregator — pure logic + thin MAVROS node adapters | `colcon`, `pytest`, `ruff` |
| `contracts/` | JSON Schemas + examples for every message crossing rosbridge; both test suites are held to them | `jsonschema` (Python tests) |
| `backend/` | .NET solution: `SwarmApi.Domain/Application/Infrastructure/ServiceDefaults/Api` | `dotnet` |
| `mcp_server/` | MCP server: swarm-level tools over `SwarmApi.Api`'s REST surface, no ROS dependency | `pytest`, `ruff` |
| `docs/adr/` | One decision record per architectural choice | — |
| `docs/architecture/` | This repo's compliance checklist and deviation register | — |
| `scripts/` | `setup.sh` (onboarding + pre-commit hook), `scan-secrets.sh` (CI secret scan, locally) | `bash`, `gitleaks` |

## Before changing code

- Changing `swarm_coordination`: keep ROS-node files (`nodes/`) as thin I/O adapters;
  put every decision in the plain, `rclpy`-free modules (`drone_controller.py`,
  `offboard.py`, `mission_planning.py`, `swarm_state.py`, `frames.py`, `formation.py`,
  ...) so it stays testable without a ROS 2 install. `test/fake_ros.py` stands in for
  `rclpy` when a test needs to drive a node. A node must not assign an attribute that
  `rclpy.node.Node` keeps its own state in (`self._publishers`, `self._timers`,
  `self._clock`, ... — `fake_ros.RCLPY_NODE_ATTRIBUTES`): rclpy lets it, then breaks.
  The dispatcher did, and never ran in SITL until the fake refused it too. Missions and
  state are in the shared world frame; only the controller node converts to a drone's
  local frame (`frames.py`: spawn offset horizontally, PX4's home vertically). A new
  MAVROS topic or service needs its plugin in `px4_config.MAVROS_PLUGINS`, or MAVROS
  never serves it.
- Changing a message that crosses rosbridge (`/swarm/mission`, `/swarm/command`,
  `/swarm/state`): change `contracts/rosbridge/` first — schema and example — then both
  sides (`RosBridgeProtocol.cs`, `mission_planning.py` / `swarm_state.py`). Both test
  suites load the same example files, so a one-sided change fails CI.
- Changing `backend/`: `Program.cs` stays a manifest (one call per capability); business
  logic goes in `SwarmApi.Application`/`SwarmApi.Domain`, not in the endpoint handlers.
  A new integration (a second bridge transport, a persistence store) is an interface in
  `SwarmApi.Application` plus a DI registration, not a base class.
- Changing `docker/Dockerfile.sim` or `docker/entrypoint.sh`: the image is built and flown
  only by `.github/workflows/sim-smoke.yml` (most of an hour cold; see
  `docs/adr/0004-ci-scope-for-simulation-stack.md`), so read PX4's own scripts for the
  pinned `PX4_VERSION` before assuming how a variable or make target behaves —
  `gz_x500` is a run target, not a build target; PX4 treats any non-empty `HEADLESS` as
  headless; its `Tools/setup/ubuntu.sh` installs Gazebo Garden, not the Harmonic
  ADR-0001 chose, and pip-installs NumPy 2, which must stay out of the runtime stage.
  Do not assume a ROS binary exists either: `ros-humble-mavros` was missing from the
  Humble apt repository, which is why MAVROS is built from a pinned release tag.
  `docker/tests/test_entrypoint.sh` checks the entrypoint's decisions against stubs;
  keep it passing and extend it with the entrypoint. A PX4 parameter every drone needs
  goes in `simulation/px4-configs/px4-rc.params` (PX4's rcS sources it from PATH), not
  in the image or an airframe copy.
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
- Python: `cd swarm_coordination && ruff check . && pytest` (`pip install jsonschema` too,
  or the contract tests skip — CI installs it).
- MCP server: `cd mcp_server && ruff check . && pytest` (no `mcp` install needed — only
  `swarm_client.py` is exercised).
- Simulation config: `docker compose -f docker/docker-compose.yml config -q` (and
  `--profile auth config -q` for the optional `authservice` services;
  `DISPLAY=:0 ... -f docker/docker-compose.gui.yml config -q` for the GUI override).
- Shell: `shellcheck docker/entrypoint.sh scripts/*.sh && bash docker/tests/test_entrypoint.sh`.

Do not attempt to build `Dockerfile.sim` or run Gazebo/PX4 SITL inside an agent sandbox:
the build takes tens of minutes and the sandbox's network policy blocks hosts it needs.
The headless stack needs no GPU, though — only the optional GUI does — so it runs on a
GitHub Actions runner instead: push, and read the `SITL smoke` job's summary and its
`sitl-logs` artifact (every tmux pane, Gazebo's log, the compose logs).
