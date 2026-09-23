# Scenarios

Each file here is one swarm scenario: a world, a timeline of events and the assertions to
hold the swarm to. The schema is [`contracts/scenario/scenario.v1.schema.json`](../contracts/scenario/scenario.v1.schema.json);
the runner is `swarm_coordination/swarm_coordination/scenarios/`. CI runs the whole
directory on every push — three seeds each, plus the mutation check — through the
repository's own scenario action (`action.yml` at the root).

```bash
# from the repository root; needs pyyaml and jsonschema
PYTHONPATH=swarm_coordination python3 -m swarm_coordination.scenarios run scenarios --seeds 3
PYTHONPATH=swarm_coordination python3 -m swarm_coordination.scenarios run scenarios --mutants
PYTHONPATH=swarm_coordination python3 -m swarm_coordination.scenarios validate scenarios
```

## What runs a scenario

**L0**: a seeded kinematic simulation of PX4 SITL and Gazebo (`scenarios/sim.py`). It keeps
the PX4 rules the swarm's software depends on: OFFBOARD and arming are refused unless
setpoints are arriving, a setpoint stream that stops drops the drone into loiter, RTL
climbs, flies home and lands, a drone on the ground disarms itself. It adds wind (a mean
plus seeded gusts), GPS noise on what the software reads, battery drain, and a network
that delivers messages a step later and drops them during a comms fault. It leaves out
attitude dynamics, motors and the estimator: a scenario that passes has shown the swarm's
*decisions* are right. Whether PX4 flies them the same way is the SITL smoke's question.

**The swarm under test** is this repository's software — `DroneController`,
`MissionSupervisor` and the swarm-state builder, the modules the ROS nodes run — driven
through the rosbridge contract, the way SwarmApi.Api drives it. The same seed reproduces a
run exactly.

## Writing one

```yaml
version: 1
name: low_battery_handover          # = the file name
description: >
  What happens, and what the swarm must do about it.
drones: 4                           # drone_n starts on its pad at (0, 3(n-1), 0)
duration_s: 150
world:                              # all optional
  wind: {mean_m_s: [1, 4, 0], gust_std_m_s: 1.5, gust_time_constant_s: 4}
  gps_noise_std_m: 0.3
  battery: {initial_pct: 100, drain_pct_per_s: 0.05}
events:                             # one per list item, at_s plus exactly one of:
  - at_s: 1
    mission: {type: waypoint, waypoints: [[0, 0, 5], [60, 0, 5]], drone_count: 3, spacing_m: 3}
  - at_s: 12
    battery: {drone: drone_1, set_pct: 18}      # fault: the battery reads 18% from now on
  - at_s: 20
    comms_loss: {drones: [drone_2], duration_s: 3}
  - at_s: 90
    command: land                               # operator: rtl | land | hold
assertions:
  - no_task_below_battery: {threshold_pct: 20, grace_s: 3}
  - mission_completes: {within_s: 140}
```

A `mission` is dispatched exactly as the API dispatches it (`contracts/rosbridge/`
`swarm_mission.v1`), so waypoints are world-frame ENU metres and `type`, `formation`,
`drone_count` and `spacing_m` mean what they mean in `POST /api/missions`.

| Assertion | Holds when | Measures |
|---|---|---|
| `min_separation: {min_m, from_s?, to_s?}` | no two **airborne** drones are ever closer than `min_m` (true positions) | the closest approach |
| `mission_completes: {within_s}` | the swarm reports the last dispatched mission complete within `within_s` of dispatch | time to complete |
| `all_landed: {by_s}` | every drone is on the ground and disarmed at `by_s` | since when |
| `no_task_below_battery: {threshold_pct, grace_s?}` | no drone keeps flying under the swarm's control (OFFBOARD) for more than `grace_s` (default 3) once its battery is below the threshold | longest time it did |
| `reaches: {drone, position, tolerance_m, by_s, from_s?}` | the drone comes within `tolerance_m` of `position` between `from_s` and `by_s` | when |
| `final_position: {drone, position, tolerance_m}` | the drone ends the run within `tolerance_m` of `position` | the distance |
| `formation_error: {max_m, leader?, from_s?, to_s?}` | each follower stays within `max_m` of its slot (leader's true position + the offset the last formation mission gives it) while both fly the formation | the largest error |
| `never_mode: {drone, mode}` | the drone's autopilot never enters `mode` | when it did |

Every violation carries the time it was measured at and the value against the threshold —
the numbers come from the trace, never from the scenario file.

**Known limitations** are written down, not deleted: `expect: fail` with an
`expect_reason` makes a scenario that must fail. If it starts passing, the runner reports
`xpass` and fails the suite, so the written-down limitation cannot quietly go out of date
(`v_formation_from_pads.yaml` is one).

## The mutation check

`--mutants` runs every scenario against deliberately broken versions of the reference swarm
(`scenarios/mutants.py`: a follower that drops its slot offset, a drone that never lands, a
supervisor that ignores batteries, a comms timeout set wrong...). A scenario no mutant
fails is reported as toothless — it would not notice the behaviour it is named after
disappearing — and a mutant every scenario passes is a behaviour the suite does not guard.
Either fails the run.

## In your own repository

The root `action.yml` is a GitHub Action that runs the same check inside your job — no
service is called and nothing leaves the runner:

```yaml
- uses: konradcinkusz/swarmsim@<ref>
  with:
    scenarios: scenarios            # your scenario files
    seeds: "3"
    sut: my_swarm.adapter:MySwarm   # optional: your swarm, see scenarios/sut.py
```

It writes a JUnit report (`swarmsim-scenarios.xml`) and the Markdown table to the job
summary, and fails the job when a scenario fails.
