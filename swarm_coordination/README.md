# swarm_coordination

ROS 2 (ament_python) package: flies a PX4 SITL + Gazebo swarm through MAVROS —
waypoint missions, leader-follower formations (line or V), and swarm commands (return to
launch, land, hold) — and reports the swarm's state back (M1/M2). It is the ROS-side half
of the rosbridge contract in [`contracts/rosbridge/`](../contracts/README.md); the other
half is `SwarmApi.Infrastructure`.

## Layout

```
swarm_coordination/
├── trajectory.py        # Vector3, step_towards — pure math
├── waypoints.py         # WaypointQueue — advance/step over a route
├── formation.py         # line/V offsets, follower targets, collision check
├── frames.py            # world ↔ a drone's local frame (spawn offset, home height)
├── px4_config.py        # reads simulation/px4-configs: namespace, MAVLink URL, spawn pose
├── offboard.py          # OffboardSequencer: stream setpoints, then OFFBOARD, then arm
├── commands.py          # rtl/land/hold → the PX4 flight mode that carries it out
├── drone_controller.py  # DroneController: everything one drone decides, per tick
├── mission_planning.py  # the /swarm/mission and /swarm/command payloads → a plan
├── supervisor.py        # MissionSupervisor: who flies what; the battery policy
├── swarm_state.py       # per-drone readings → the /swarm/state payload
├── scenarios/           # the scenario instrument: L0 simulator, SUT protocol, runner, mutants
└── nodes/               # thin rclpy adapters over the modules above
    ├── drone_controller_node.py        # one per drone: MAVROS in, setpoints out
    ├── mission_dispatcher_node.py      # one per swarm: /swarm/mission → per-drone tasks
    └── swarm_state_aggregator_node.py  # one per swarm: telemetry → /swarm/state
launch/spawn_swarm.launch.py  # MAVROS + a controller per drone, dispatcher, aggregator
test/                         # pytest; nodes/ only through the stand-in in fake_ros.py
```

Every module above `nodes/` is free of `rclpy` and unit tested without a ROS 2 install.
The nodes are tested too — `test/fake_ros.py` stands in for `rclpy` and the message
packages, so `test/test_nodes_with_fake_ros.py` wires real node code to a fake bus and
checks what they publish and which MAVROS services they call. See `conftest.py` and
`pyproject.toml` for how. The fake keeps a node's publishers, timers, clock and logger in
the attributes rclpy keeps them in, and refuses a node that assigns one of those names —
rclpy allows it and fails later, which is how the dispatcher died at start in every SITL
smoke run until 2026-09-22.

## How a mission flies

1. `SwarmApi.Api` publishes the mission on `/swarm/mission` (a JSON string —
   `contracts/rosbridge/swarm_mission.v1.schema.json`).
2. `mission_dispatcher_node` hands it to `supervisor.MissionSupervisor`, which plans it
   (`mission_planning.plan_mission`) onto the drones fit to fly — in id order, skipping
   any whose battery is already below the threshold (20 %). A waypoint mission gives
   each drone its own copy of the route, offset sideways by the formation spacing; a
   formation mission gives the first of them the route and every other one a slot
   relative to it. Each drone gets its task on `/<drone>/mission/assignment` or
   `/<drone>/mission/slot`; the active mission is latched on `/swarm/active_mission`.
   A mission that needs more fit drones than are running is rejected and logged.
   While it flies, a drone whose battery drops below the threshold hands the rest of
   its task to an idle drone and is sent home (`rtl`); with nobody idle, it is sent home
   anyway and its task is reported dropped.
3. Each `drone_controller_node` runs its `DroneController` at 10 Hz. It streams
   setpoints to `mavros/setpoint_position/local` before asking for OFFBOARD — PX4
   rejects the switch otherwise — then arms, retrying both until MAVROS reports them.
   It flies the task and, when it is done (the last waypoint reached, or the leader
   landed), hands the vehicle to PX4's `AUTO.LAND`. A command on `/swarm/command`
   (`rtl`, `land`, `hold`) pre-empts all of it with the matching PX4 mode. A follower
   that stops hearing its leader holds the slot it last knew; if the leader is still
   silent after 5 s (`comms_timeout_s`), it gives up and returns to launch.
4. `swarm_state_aggregator_node` combines every drone's position, armed state, flight
   mode, battery and mission progress into `/swarm/state` at 5 Hz. A mission is complete
   when every assigned drone has finished its task and disarmed.

**Frames.** PX4 reports each drone's position relative to where it spawned, so five
drones on five pads all report roughly "(0, 0, …)" before takeoff. Everything crossing
the package boundary — missions in, state out — is in the shared world frame (ENU,
metres, the Gazebo world's origin); `frames.py` converts with each drone's spawn offset,
which `px4_config.py` reads from the same `drone_<n>.env` files `docker/entrypoint.sh`
spawned the drone from. Heights are measured from PX4's **home**
(`mavros/home_position/home`), not from the local origin: PX4 fixes the origin's
altitude from whatever height its estimator had reached at the first GNSS fix, and in
the SITL smoke that put drones standing on their pads up to 2.6 m off. PX4 re-takes
home on the ground and at every arming, so a world height is the height above the pad.

**MAVROS plugins.** Each drone's MAVROS loads only the plugins the nodes use
(`px4_config.MAVROS_PLUGINS`, passed as an allowlist by the launch file); a test checks
every `mavros/...` name in `nodes/` against that table, because a topic whose plugin is
not loaded is simply never published.

## Running it

In the simulation image this all starts on its own: `docker/entrypoint.sh` launches
`spawn_swarm.launch.py with_mavros:=true` after the PX4 instances (disable with
`SWARM_COORDINATION=0`), and `docker compose exec sim tmux attach -t coordination`
shows its output. Without the API, a mission can be published by hand from inside the
container:

```bash
docker compose exec sim bash
source /opt/swarmsim/ws/install/setup.bash
ros2 topic pub --once /swarm/mission std_msgs/String "{data: '{\"version\": 1,
  \"mission_id\": \"3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c\", \"type\": \"waypoint\",
  \"formation\": \"line\", \"waypoints\": [[0, 0, 5], [10, 0, 5]], \"drone_count\": 1,
  \"spacing_m\": 2.0}'}"
ros2 topic echo /swarm/state
```

Outside the image, it needs a ROS 2 Humble workspace with MAVROS and its geoid dataset
(`sudo geographiclib-get-geoids egm96-5`). `sudo apt install ros-humble-mavros` is the
usual way to get MAVROS, but in September 2026 the Humble apt repository had no MAVROS
package, so `docker/Dockerfile.sim` builds it from its release tag with rosdep and colcon —
the same steps work outside the image. Then:

```bash
colcon build --packages-select swarm_coordination
source install/setup.bash
ros2 launch swarm_coordination spawn_swarm.launch.py with_mavros:=true \
    px4_config_dir:=/path/to/swarmsim/simulation/px4-configs drone_count:=3
```

Each drone's MAVROS connects to its PX4 instance on the ports PX4 derives from the
instance index (`udp://:14540+i@127.0.0.1:14580+i`, `tgt_system` = i + 1), so the only
per-drone input is the `drone_<n>.env` file.

## Scenario testing

`scenarios/` is the instrument that flies the YAML scenarios in the repository's
[`scenarios/`](../scenarios/README.md) directory ([ADR-0008](../docs/adr/0008-scenario-instrument.md)):

| Module | What it is |
|---|---|
| `sim.py` | L0: a seeded kinematic stand-in for PX4 SITL + Gazebo — PX4's OFFBOARD, arming, failsafe, RTL and auto-disarm rules; wind, GPS noise, battery, and nothing more |
| `sut.py` | The system-under-test protocol, and `ReferenceSwarm`: the modules above, wired as the ROS nodes wire them |
| `spec.py` | Scenario files, validated against `contracts/scenario/scenario.v1.schema.json` |
| `harness.py` | `run_scenario(spec, sut, seed)` → verdict and trace; a lossy network between the drones |
| `assertions.py` | Measurements over the trace: separation, completion, landing, battery, formation error... |
| `mutants.py` | Broken versions of the reference swarm, for the mutation check |
| `runner.py`, `__main__.py` | The suite, JUnit/JSON/Markdown reports, and `python -m swarm_coordination.scenarios` |

The scenarios test this package's product code — the battery policy lives in
`supervisor.py` and the comms-loss policy in `drone_controller.py`, where the ROS nodes
run them too — so a scenario can only pass by the swarm doing the right thing.

## Development

```bash
pip install ruff pytest jsonschema pyyaml
ruff check .
pytest
```

Both run in CI (`.github/workflows/ci.yml`, job `python`) on every push and PR.
`jsonschema` and `pyyaml` are for the contract and scenario tests, which skip without
them locally, never in CI; the ROS nodes need neither.
