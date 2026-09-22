# Scenario study: does the swarm do what it says under faults, and would the suite notice if it stopped?

A study run with the scenario instrument ([ADR-0008](../adr/0008-scenario-instrument.md))
on the reference swarm — this repository's own software, the modules the ROS nodes run.
Two questions:

1. **Behaviour.** Under wind, GPS noise, comms loss, battery faults, operator commands
   and ten drones instead of three, does the swarm keep its separation, finish its
   missions, hand work over and go home when its own rules say it must?
2. **Adequacy.** Would these scenarios notice if one of those behaviours broke?

## Method

- **Simulation (L0).** A seeded kinematic model of PX4 SITL and Gazebo: point masses
  under a PX4-like autopilot (proportional position loop, 5 m/s horizontal, 3 m/s
  climb; PX4's OFFBOARD, arming, offboard-loss, RTL and auto-disarm rules), wind with
  Ornstein-Uhlenbeck gusts of which the loop cancels 80 %, Gaussian GPS noise on what the
  software reads, 0.05 %/s battery drain in the air, and a network that delivers on the
  next 0.1 s step and drops everything to and from a drone during a comms fault.
- **System under test.** `ReferenceSwarm`: `DroneController` per drone,
  `MissionSupervisor` and the swarm-state builder on the ground, driven through the
  rosbridge contract exactly as SwarmApi.Api drives the real swarm.
- **Scenarios.** The ten files in [`scenarios/`](https://github.com/konradcinkusz/swarmsim/tree/main/scenarios),
  each run with seeds 1–5. A scenario passes only if every seed passes.
- **Mutation analysis.** Eight hand-written regressions of the reference swarm, one
  behaviour each ([`mutants.py`](https://github.com/konradcinkusz/swarmsim/blob/main/swarm_coordination/swarm_coordination/scenarios/mutants.py)),
  run against every scenario the reference swarm passes (seed 1).

Reproduce everything below from the repository root (needs `pyyaml` and `jsonschema`):

```bash
PYTHONPATH=swarm_coordination python3 -m swarm_coordination.scenarios run scenarios \
    --seeds 5 --mutants --json results.json
```

## Results

Run of 2026-09-22: **9 passed, 1 expected failure; 8 of 8 mutants caught.** 50 reference
runs took 3.2 s of wall time in total.

| Scenario | Outcome | Measured (seeds 1–5) | Mutants it caught |
|---|---|---|---|
| `waypoint_lanes` | passed | complete in 24.8 s; closest approach 3 m; landed 0.46 m from lane end | never_lands, no_frame_conversion |
| `formation_line` | passed | closest approach 2.12 m; worst slot error 2.2 m; complete in 36.8 s | never_lands, formation_offset_dropped, no_frame_conversion |
| `formation_line_in_wind` | passed | closest approach 2.10–2.13 m; worst slot error 2.24–2.26 m; complete in 40.3–64 s | never_lands, formation_offset_dropped, no_frame_conversion |
| `follower_comms_blip` | passed | closest approach 2.12 m; complete in 46.8 s; no RTL | never_lands, formation_offset_dropped, hair_trigger_comms_timeout |
| `follower_jammed_goes_home` | passed | followers back on their pads at 44.9–45.4 s; all landed by 48.8 s | never_lands, formation_offset_dropped, no_comms_timeout |
| `low_battery_handover` | passed | low drone under swarm control 1 s after crossing 20 %; home at 31.8 s; mission complete in 54.3 s | never_lands, no_frame_conversion, deaf_to_commands, no_battery_reallocation, battery_blind |
| `plan_around_low_battery` | passed | drone_1 never flew; lanes flown by drones 2–4; complete in 25.2 s | never_lands, no_frame_conversion, battery_blind |
| `operator_land_in_place` | passed | all down at t = 23.8 s, 8.8 s after "land" | deaf_to_commands |
| `scale_ten_lanes` | passed | closest approach 2.67–2.79 m; complete in 30–30.3 s | never_lands, no_frame_conversion |
| `v_formation_from_pads` | **expected failure** | closest approach **0.48 m** | — |

## Findings

1. **A V formation launched from the pads is a near collision.** Every pad lies on one
   side of the leader, but the V puts every other follower on the far side, so `drone_3`
   heads for a slot beyond the leader on a line that runs through `drone_2`, which is
   heading for its own slot. They pass 0.48 m apart — about the width of an x500 — 3 s
   after dispatch, less than half a metre off the ground. The swarm assigns slots without
   looking at where the drones start and has no deconfliction in flight. Kept in the suite as an
   expected failure; the fix is a planning decision (pick the leader and each
   follower's side from the pad layout, or deconflict the plan before dispatch), and the
   SITL smoke already avoids it by flying a line.
2. **Followers trail their slots by ≈ 2.2 m at cruise.** That is the lag of a proportional
   loop chasing a moving point: 2 m/s ÷ 1/s. Wind and GPS noise add only 0.05 m to it. The
   formation-error assertions allow 2.5–3 m so they fail a formation that has fallen
   apart, not this lag. A lead term — aim at where the leader will be, not where it
   was — would close most of it.
3. **A crosswind stretches missions by up to 75 % and pushes the route 8 m sideways.**
   Calm, the line formation completes in 36.8 s; in a 4 m/s crosswind with 1.5 m/s gusts,
   40–64 s. Two mechanisms, both visible in the traces. The position loop is left with a
   steady offset of about 0.8 m in that wind, larger than the 0.5 m waypoint acceptance
   radius, so a drone can hold station near a waypoint until a gust lull lets it in — the
   leader of the slowest run hovered at its first waypoint until t = 24.6 s, against 7.7 s
   in calm air. And the controller re-aims its setpoint from wherever it has drifted to
   rather than steering back onto the line between waypoints, so the leader flew
   7.4–8.5 m off that line in every seed. PX4's position loop has the integral action
   L0's lacks, so both effects should be smaller for real — they are the first things to
   measure at L1, and cross-track correction is a candidate for the controller either way.
4. **The fault policies behave as written.** A 3 s comms loss is ridden out without a
   return home; a permanent one sends both followers home 5 s later and they land on
   their own pads while the leader finishes alone. A drone whose battery drops below
   20 % stays under the swarm's control for 1 s — the supervisor's decision period —
   before it is sent home and an idle drone takes the rest of its lane; a drone already
   low when the mission arrives is never given a task.
5. **The suite has teeth, unevenly.** Every mutant is caught, and every passing scenario
   catches at least one. `never_lands` and `no_frame_conversion` are caught almost
   everywhere; `deaf_to_commands` only by the two scenarios in which a drone is commanded
   (the operator's "land", the supervisor's "rtl"), and `hair_trigger_comms_timeout` by
   one. Those behaviours are one or two scenarios deep.

## Threats to validity

- **L0 is not PX4.** No attitude dynamics, no estimator, no integral action in the
  position loop, point masses that pass through each other (separation is measured, not
  simulated). Findings 2 and 3 are partly properties of the model — finding 3 most of
  all. The SITL smoke is the
  check that PX4 behaves like L0 assumes, and today it covers two missions, not ten.
- **The mutants are hand-written.** They are plausible regressions, one behaviour each,
  chosen by the author of the scenarios — so "8 of 8 caught" says the suite guards what
  its author thought to break, not that it guards everything.
- **Five seeds** show spread, not distributions; wind and noise are the only randomness.
- **Thresholds were set by the same author**, after the first run for the formation-error
  ones (finding 2 explains the number rather than hiding it).

## Next

- **L1:** fly the same scenario files through SwarmApi.Api against the SITL stack. The
  format was shaped for it — a scenario's missions are the API's missions.
- Fix finding 1 in the planner and turn `v_formation_from_pads` into a passing scenario.
- Generated mutants alongside the hand-written ones, and more seeds with distributions
  reported instead of ranges.
