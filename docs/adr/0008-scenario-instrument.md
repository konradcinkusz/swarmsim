# ADR-0008: The scenario instrument — L0 simulation, a system-under-test seam, mutation adequacy

## Status

Accepted (2026-09-22). Supersedes the scenario contract the scenario library (issues
#12–#18) was built on.

## Context

The scenario library had seven scenarios and a `Scenario(name, description, run())`
contract. Read closely, none of them tested the swarm:

- each carried its own copy of the behaviour it was named after — the low-battery
  reallocation, the comms-jamming fallback — so it tested that copy, and the swarm could
  lose the behaviour without any scenario noticing (the jamming policy, for one, existed
  nowhere but in its scenario);
- each built its own positions by hand and "checked" them at a timestamp typed into the
  file (`_DISTURBANCE_TIMESTAMP_S = 12.5`), so a violation's time was declared, not
  measured;
- `run()` took no arguments, so there was no way to run a scenario against anything but
  itself — not another seed, not another swarm.

That is not a testing product; it is seven unit tests with a shared dataclass. The
standards say the same thing in their own terms: TESTING-STRATEGY.md §1 asks what a test
would catch, and P13 asks for tests at the layer that holds the logic.

Two further facts shape the answer. PX4 SITL is the real thing but costs an hour to build
and minutes per run (ADR-0004 and its amendment) — it cannot be the instrument run on
every push. And the product this points at (ADR-0006, ADR-0007) sells running *someone
else's* swarm through scenarios, so the seam between the scenario and the swarm is the
product's core interface, not an implementation detail.

## Decision

**A scenario is data, run against a system under test in a seeded simulation; its
adequacy is shown by the broken swarms it catches.**

- **Scenarios are YAML**, validated against `contracts/scenario/scenario.v1.schema.json`
  (P11: the contract lives in `contracts/`, next to the rosbridge ones). A world, a
  timeline of events — missions, operator commands, injected faults — and assertions.
  Writing one needs no Python.
- **`run(spec, sut, seed) → Verdict + Trace`.** The trace is the truth of the simulated
  world at every 0.1 s step next to what the swarm *reported*; assertions read only the
  trace, so every violation carries a measured value and the time it was measured at.
  The same seed reproduces a run bit for bit; randomness comes from named streams.
- **L0, a kinematic simulation, not a physics engine.** Point masses under a PX4-like
  autopilot that keeps the rules the swarm's software depends on (no OFFBOARD or arming
  without a setpoint stream; offboard loss drops to loiter; RTL climbs, returns, lands;
  auto-disarm), plus wind with seeded gusts, GPS noise on what the software reads,
  battery drain and a lossy network. It checks decisions; the SITL smoke (L1) checks
  that PX4 flies them. The whole suite with three seeds and the mutation check runs in
  about seven seconds.
- **The system under test is behind a protocol** (`scenarios/sut.py`): one
  `DroneSoftware` per drone, reading its own autopilot and exchanging messages; one
  `GroundSoftware` taking missions and commands in the rosbridge contract's format and
  reporting swarm state in it. The simulator owns the network between them, so it can
  delay and drop messages. `ReferenceSwarm` is this repository's swarm, wired from the
  same modules the ROS nodes run; another swarm plugs in with `--sut module:attribute`.
- **Behaviour the scenarios test moved into the product.** The battery policy is
  `supervisor.MissionSupervisor` (which `mission_dispatcher_node` now runs, so the real
  swarm reallocates too); the comms-loss policy is part of `DroneController`. A scenario
  can only pass by the product doing the right thing.
- **Mutation adequacy.** `scenarios/mutants.py` holds plausible regressions of the
  reference swarm, one behaviour each. The suite fails if a scenario catches no mutant
  (toothless) or a mutant passes every scenario (unguarded). Known limitations stay in
  the suite as `expect: fail` with a reason; if one starts passing it is reported as
  `xpass` and fails the suite until someone updates it.
- **It runs where the customer's code runs.** The root `action.yml` is a GitHub Action
  that installs the runner and flies the caller's scenarios inside their job — no hosted
  service, nothing leaves the runner — and writes a JUnit report and a job summary. CI
  runs the repository's suite through that action and checks both its pass and its fail
  path. The mission smoke action moved to `actions/mission-smoke/`.

## Consequences

- The old scenario modules and their tests are gone; their intent lives on as YAML
  scenarios that exercise the product (`scenarios/`), and the study that reads their
  results is `docs/research/scenario-study.md`.
- The first real finding came with the first run: a V formation launched from the row of
  pads makes a follower cross its neighbours (0.48 m closest approach). It is recorded as
  an expected failure, not fixed here — the fix is a planning decision (leader and sides
  from the pad layout, or plan-time deconfliction), not a threshold.
- L0's fidelity is the instrument's main threat to validity: a follower's lag behind its
  slot (≈ speed ÷ position gain) and RTL's shape are modelled, not measured. The honest
  next step is L1: the same scenario files flown against the SITL stack through the API,
  which the scenario format was shaped for (its missions are the API's missions).
- PyYAML and jsonschema become runner dependencies. They are needed by
  `scenarios/spec.py` only; nothing the ROS nodes import touches them.

Worked example: `scenarios/low_battery_handover.yaml`, `swarm_coordination/swarm_coordination/supervisor.py`,
`swarm_coordination/test/test_scenario_runner.py`.

## Amendment — 2026-10-03: a known limitation belongs to a swarm, not to a scenario file

`expect: fail` in a scenario file is a statement about one swarm, this repository's
reference swarm. Flown by another swarm, the same scenario can be a gap that swarm has
closed (reported `xpass`, which fails the suite) or can fail for a reason of that swarm's
own with nothing written down to excuse it, and the run store compared the two runs as a
regression where one of them was a fix (findings F4 and F12 of swarmsim-lab). Whether a
failure is a regression or a known gap belongs to the (scenario, swarm) pair.

The scenario files keep the reference swarm's expectations, as before. `--expect FILE`
(the action's `expect` input) replaces them with the swarm under test's own: a YAML file,
`contracts/scenario/expectations.v1.schema.json`, that names the scenarios the swarm is
expected to fail and gives a reason for each. A scenario named there must fail, every other
must pass, and the files' own `expect` is not consulted. The expectation is applied as the
scenarios are loaded, so the outcomes, the mutation check, the reports and a stored run all
carry the one that applied, and the report contract is unchanged. ADR-0011's comparison,
which reads stored outcomes, follows: a swarm that closes the reference's gap compares as
`changed` (the expectation itself changed) instead of `regressed`.

A name that matches no scenario in the run is reported and ignored, not an error: one file
can serve a run of a few scenarios. The cost is that a stale entry survives until someone
reads the report; a misspelt one at least leaves its scenario expected to pass, so the
suite goes red and the report names the unknown entry.

## Amendment — 2026-10-03 (later): another swarm brings its own mutants

The mutation check was the reference swarm's. `--mutants` breaks this repository's swarm, so
a swarm given with `--sut` could not have one, and its authors wrote a runner of their own for
it (finding F1 of swarmsim-lab). `--mutants-from MODULE:ATTR` (the action's `mutants-from`)
runs the same check with a sequence of `Mutant(name, breaks, sut)` that the swarm's author
provides, each `sut` a broken version of the swarm under test. Flown through it, the five
mutants of that lab's swarm and its reference swarm gave the check the lab's own test had
reached: each mutant caught by the scenario written for it, every scenario holding at least
one.

- It is a separate option and not `--mutants MODULE:ATTR`: an option with an optional value
  takes the next word, so `run --mutants scenarios` would read the scenario directory as
  the mutants.
- The two exclude each other, and `--mutants` with `--sut` is still refused, now with a pointer
  to the new option.
- `Mutant.sut` is typed as any swarm, which is how the runner always treated it.
- The runner checks the shape of what it is given, not its worth. Which breakages are
  plausible is the swarm author's judgement, as it was for this repository's eight. The check
  makes each one answer to a scenario, and each scenario to a mutant.

## Amendment — 2026-10-03 (later still): planning is a seam

A swarm that plans differently from the reference had to rewrite the supervisor's private
plan after `start()` and override its private `_hand_over()` (finding F8 of swarmsim-lab).
`MissionSupervisor` now takes a `planner`: given the mission, the drones fit to fly it and
where those have reported they are, it returns the `MissionPlan`. `observe_position` is how
the supervisor learns where they are, and the L0 ground software feeds it from the telemetry
it already receives. `ReferenceSwarm(planner=...)` is the seam for a swarm under test.

- With no planner nothing changes: the lowest ids fly and the lowest id leads.
- The supervisor checks what the planner returns, because the plan drives actions and later
  hand-overs: the mission's id, exactly `drone_count` drones, all of them offered, no drone
  both flying a path and following, every leader flying a path, no empty path. A plan that
  fails a check, or a planner that raises, rejects the mission with the reason, as a
  mission that too few drones can fly is rejected, and the mission in flight flies on.
- The planner is offered every drone fit to fly and the positions reported so far, which may
  lack some. What to do about a drone it knows nothing about, plan as the default does or not,
  is the planner's decision.
- A hand-over after a low battery is still the supervisor's: the replacement takes the place
  of the drone going home. A swarm whose planner chooses roles from positions may want to
  re-plan there too, which is a second seam and not built here.
- The ROS dispatcher node builds no planner, so on a drone it changes nothing. Letting it
  load one by name (finding F6) is the step from L0 to SITL.

The lab's start-time planning, written as a planner and run beside its own subclass over 23
scenarios and 3 seeds, gave 69 identical traces.

