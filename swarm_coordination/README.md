# swarm_coordination

ROS 2 (ament_python) package: waypoint following and leader-follower formation for a
PX4 SITL + Gazebo swarm (M1/M2).

## Layout

```
swarm_coordination/
├── trajectory.py     # Vector3, step_towards — pure math, no rclpy import
├── waypoints.py       # WaypointQueue — advance/step over a route
├── formation.py       # line/V offsets, follower targets, collision check
├── scenarios/          # scenario-testing contract (Scenario/Verdict/Violation)
└── nodes/              # thin rclpy adapters over the three modules above
    ├── waypoint_follower_node.py
    └── formation_commander_node.py
launch/spawn_swarm.launch.py   # spawns one node set per drone_<n> namespace
test/                           # pytest against trajectory/waypoints/formation only
```

`test/` never imports `nodes/` — that is what lets `pytest` (and CI) run these tests
with plain `pip install pytest`, no ROS 2 installation required. See `conftest.py` and
`pyproject.toml` for how.

## Scenario testing

`scenarios/` is the contract a swarm-testing-as-a-service scenario library implements
against: a `Scenario` is a named, self-contained test case (it owns its own setup and
perturbation, so evaluating it is just `scenario.run()`), returning a `Verdict`
(pass/fail plus, on failure, the concrete `Violation`s a future report/replay layer
will render). There's no central registry to register into — each scenario is its own
module that only imports from `scenarios/`, so multiple scenarios can be added in
parallel without touching a shared file. See `scenarios/example_static_formation.py`
for a minimal reference scenario, and `test/test_scenario_contract.py` for the contract
tests.

## Prerequisites to actually run a node

Building and launching the nodes (not the unit tests) needs a ROS 2 Humble workspace
with `mavros` bridging each PX4 SITL instance over MAVLink:

```bash
sudo apt install ros-humble-mavros ros-humble-mavros-extras
sudo /opt/ros/humble/lib/mavros/install_geographiclib_datasets.sh

# One MAVROS instance per drone. PX4 SITL logs the exact MAVLink UDP port each running
# instance opened for a companion/offboard link on startup (`docker compose exec sim
# tmux attach -t drone_1` and read the `mavlink` module's startup lines) — the default
# scheme offsets both the companion link (base 14540) and the GCS link (base 14550) by
# the instance index, but confirm against that log rather than assuming it, since it is
# a PX4 SITL default and not a contract this repository owns:
ros2 run mavros mavros_node --ros-args \
    -r __ns:=/drone_1 \
    -p fcu_url:=udp://:14540@127.0.0.1:14540

colcon build --packages-select swarm_coordination
source install/setup.bash
ros2 launch swarm_coordination spawn_swarm.launch.py mode:=waypoint drone_count:=3
```

This step is intentionally outside `docker/Dockerfile.sim`: it needs a running Gazebo
instance to bridge against, is only ever exercised manually (per
`docs/adr/0004-ci-scope-for-simulation-stack.md`), and keeping infra (MAVLink endpoint
wiring) separate from coordination logic (this package) means either can be swapped —
a different bridge transport, a different formation algorithm — without touching the
other.

## Development

```bash
pip install ruff pytest
ruff check .
pytest
```

Both run in CI (`.github/workflows/ci.yml`, job `python`) on every push and PR.
