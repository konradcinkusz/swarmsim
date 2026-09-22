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
| `contracts/` | JSON Schemas + examples for every message crossing rosbridge, and the scenario file format | `jsonschema` (Python tests) |
| `scenarios/` | Swarm scenarios (YAML) run in L0 on every push, with the mutation check | `python -m swarm_coordination.scenarios` |
| `action.yml`, `actions/mission-smoke/` | GitHub Actions: the scenario check (runs in the caller's job), the running-API smoke test | composite actions |
| `backend/` | .NET solution: `SwarmApi.Domain/Application/Infrastructure/ServiceDefaults/Api` | `dotnet` |
| `mcp_server/` | MCP server: swarm-level tools over `SwarmApi.Api`'s REST surface, no ROS dependency; `BEHAVIOUR.md` is its normative tool table | `pytest`, `ruff` |
| `e2e/` | The dashboard in a real browser (Playwright, Chromium) against a running API | `pytest`, `playwright` |
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
- Changing flight or swarm behaviour (anything the ROS nodes decide): the scenarios in
  `scenarios/` fly the same modules in L0 (`swarm_coordination/scenarios/`, ADR-0008).
  Run them with `--mutants`. A new behaviour needs a scenario that fails without it and
  a mutant in `scenarios/mutants.py` that proves so; a policy lives in product code
  (`supervisor.py`, `drone_controller.py`), never only inside a scenario. A known gap is
  written down as `expect: fail` with a reason, not deleted.
- Changing a message that crosses rosbridge (`/swarm/mission`, `/swarm/command`,
  `/swarm/state`): change `contracts/rosbridge/` first — schema and example — then both
  sides (`RosBridgeProtocol.cs`, `mission_planning.py` / `swarm_state.py`). Both test
  suites load the same example files, so a one-sided change fails CI.
- Changing `backend/`: `Program.cs` stays a manifest (one call per capability); business
  logic goes in `SwarmApi.Application`/`SwarmApi.Domain`, not in the endpoint handlers.
  A new integration (a second bridge transport, a persistence store) is an interface in
  `SwarmApi.Application` plus a DI registration, not a base class.
- Adding or changing an endpoint: give it a row in `docs/architecture/API-SURFACE.md`
  first — its class (read, plan, approval, gated-write, write, safety-write), whether
  Enforced mode lets it through without a token, whether it honours `Idempotency-Key`
  (every POST does: `.WithIdempotency()`). `ApiSurfaceTests` fails on an endpoint without
  a row or one that disagrees with it. Nothing that makes drones fly may be reachable by
  an agent without a person's approval (`docs/adr/0009-agent-write-gate.md`); stopping
  (abort, land-all) is never gated.
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
  package, 2.x — `MCPServer`, not the removed `FastMCP`) thin; the tools and their
  classification live in `tools.py`, requests and failures in `swarm_client.py`, both
  free of the `mcp` import so `pytest` exercises them with no network and no `mcp`
  install — mirrors the `swarm_coordination` node/pure-logic split. A new tool needs a
  row in `mcp_server/BEHAVIOUR.md` whose class matches the endpoint it calls; there is no
  tool that approves a plan or calls `POST /api/missions`, and adding one fails
  `test_behaviour.py` on purpose.

## Local verification

- `.NET`: `dotnet test backend/SwarmPlatform.sln`. On an Ubuntu 24.04 sandbox whose
  network policy blocks Microsoft's download hosts, `apt-get install dotnet-sdk-8.0`
  (Ubuntu's own archive) usually still works; otherwise let CI run it.
- Python: `cd swarm_coordination && ruff check . && pytest` (`pip install jsonschema pyyaml`
  too, or the contract and scenario tests skip — CI installs both).
- Scenarios: `PYTHONPATH=swarm_coordination python3 -m swarm_coordination.scenarios run
  scenarios --seeds 3 --mutants` (seconds; exit 0 only if every scenario met its
  expectation and every mutant was caught).
- MCP server: `cd mcp_server && ruff check . && pytest` (no `mcp` install needed — only
  `swarm_client.py` and `tools.py` are exercised).
- Dashboard (browser): `pip install playwright pytest && python -m playwright install
  chromium && pytest e2e -v` — starts the API itself with `dotnet run`; set
  `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to use a Chromium already on the machine.
- Simulation config: `docker compose -f docker/docker-compose.yml config -q` (and
  `--profile auth config -q` for the optional `authservice` services;
  `DISPLAY=:0 ... -f docker/docker-compose.gui.yml config -q` for the GUI override).
- Shell: `shellcheck docker/entrypoint.sh scripts/*.sh && bash docker/tests/test_entrypoint.sh`.

Do not attempt to build `Dockerfile.sim` or run Gazebo/PX4 SITL inside an agent sandbox:
the build takes tens of minutes and the sandbox's network policy blocks hosts it needs.
The headless stack needs no GPU, though — only the optional GUI does — so it runs on a
GitHub Actions runner instead: push, and read the `SITL smoke` job's summary and its
`sitl-logs` artifact (every tmux pane, Gazebo's log, the compose logs). A first flight
that fails with `stalled drone_N` hit PX4's own simulated-sensor stall (docs/adr/0004,
2026-09-23): the job flies once more on a fresh stack. Any other failure is real.
