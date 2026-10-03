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

The runner also runs from an install, in any directory — the schema ships inside the
package — so scenarios and a swarm under test can live in another repository:

```bash
pip install ./swarm_coordination pyyaml jsonschema
python -m swarm_coordination.scenarios run my_scenarios --sut my_package:MySwarm --seeds 3 \
  --expect my_package/expectations.yaml     # optional: what it is expected to fail
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
| `min_separation: {min_m, from_s?, to_s?}` | no two **airborne** drones are ever closer than `min_m` (true positions); it fails if fewer than two drones are airborne in the window, because nothing was measured | the closest approach |
| `mission_completes: {within_s}` | the swarm reports the last dispatched mission complete within `within_s` of dispatch | time to complete |
| `all_landed: {by_s}` | every drone is on the ground and disarmed at `by_s` | since when |
| `no_task_below_battery: {threshold_pct, grace_s?}` | no drone keeps flying under the swarm's control (OFFBOARD) for more than `grace_s` (default 3) once its battery is below the threshold | longest time it did |
| `reaches: {drone, position, tolerance_m, by_s, from_s?}` | the drone comes within `tolerance_m` of `position` between `from_s` and `by_s` | when |
| `final_position: {drone, position, tolerance_m}` | the drone ends the run within `tolerance_m` of `position` | the distance |
| `formation_error: {max_m, leader?, from_s?, to_s?}` | the drones fit the last formation mission's shape within `max_m`: in every frame where exactly `drone_count` drones fly under offboard control, some drone is the apex and the others are matched to the slots around it (its true position + the formation's offsets), the largest distance of any drone from its slot as small as it can be. Who leads and who takes which slot is the swarm's choice, so the reference swarm's roles are not assumed; `leader` pins the apex. A window with no such frame fails, because nothing was measured | the largest error of the closest fit |
| `never_mode: {drone, mode}` | the drone's autopilot never enters `mode` | when it did |

Every violation carries the time it was measured at and the value against the threshold —
the numbers come from the trace, never from the scenario file.

**A distance check that measured nothing fails.** `min_separation` and `formation_error`
are violations, not passes, when their window held nothing to measure: a window typed a few
seconds after the swarm landed would otherwise pass for any swarm. The violation says when
the formation did fly, so the window can be fixed from the report. `never_mode` and
`no_task_below_battery` claim an absence, so for them nothing happening is the pass.

**Known limitations** are written down, not deleted: `expect: fail` with an
`expect_reason` makes a scenario that must fail. If it starts passing, the runner reports
`xpass` and fails the suite, so the written-down limitation cannot quietly go out of date
(`v_formation_from_pads.yaml` is one).

**A known limitation is one swarm's.** The `expect` in a scenario file records what this
repository's reference swarm fails. Another swarm flown against the same scenarios has
limitations of its own, and may have closed the reference's, so it brings its own file and
passes it with `--expect` (the action's `expect` input):

```yaml
version: 1    # contracts/scenario/expectations.v1.schema.json
expect_fail:
  follower_jammed_goes_home: >
    The scenario jams drone_2 and drone_3 by name and expects them to be followers. This
    swarm picks its leader from where the drones stand, so one of them can be the leader.
```

With it, the scenario files' own `expect` is ignored: the scenarios the file names must
fail and every other must pass. A swarm that closes the reference's gap gets a plain
`passed`, not an `xpass` that only editing the reference's scenario file would clear, and is
held to it from then on; one that fails a scenario for its own reason has to say why, in
writing. A name that matches no scenario in the run is listed in
the report and ignored, so one file can serve a run of a few scenarios; a misspelt name
leaves the scenario it meant to excuse expected to pass. Keep the file with the swarm: one
kept among the scenarios is not run as one. The outcome each scenario met is what the
report, the JUnit file and a stored run carry, so `GET /api/scenario-runs/compare` reads
a swarm that closed the reference's gap as `changed` (the expectation itself changed), not
as a regression. [`examples/expectations.yaml`](../contracts/scenario/examples/expectations.yaml)
is the schema's example.

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
    expect: my_swarm/expectations.yaml   # optional: what it is expected to fail
    include-swarmsim-scenarios: "true"   # optional: swarmsim's own scenarios too
```

It writes a JUnit report (`swarmsim-scenarios.xml`) and the Markdown table to the job
summary, and fails the job when a scenario fails.

`include-swarmsim-scenarios` flies this repository's own scenarios, at the version you
pinned, against your swarm as well — they are the same ones, and their `expect` is the
reference swarm's, so list your swarm's known failures in `expect`. That file then covers
every scenario in the run, yours included, and scenario names are unique across the run, so
yours must not reuse theirs. Set `scenarios` to nothing to fly only swarmsim's.
