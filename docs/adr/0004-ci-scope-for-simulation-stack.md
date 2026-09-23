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

## Amendment — 2026-09-22: the trigger fired, and part of the reasoning was wrong

The decision above rested partly on this repository's *agent sandbox* being unable to
reach PX4's, ROS's and Gazebo's hosts. That is a property of the sandbox, not of a GitHub
Actions runner, which reaches all of them. And the "needs a GPU" constraint applies only
to the Gazebo GUI: PX4 SITL with a headless Gazebo server runs on CPU, and the x500's
sensors (IMU, barometer, magnetometer, GNSS) need no rendering. The recorded trigger — a
runner able to build the image and fly a drone — was therefore already met.

What changed: `.github/workflows/sim-smoke.yml` builds `docker/Dockerfile.sim` (layers
cached in GHCR), starts the compose stack with three drones, headless, and runs
`docker/tests/sitl_smoke.py` against `SwarmApi.Api`: every drone at its pad in the world
frame (M1), a waypoint mission that takes off, flies its lanes, lands and reports
Completed (M0, M3), the p95 age of state at the API (M3's "< 1 s", measured rather than
asserted), and an abort that lands a flying formation. It runs on pull requests touching
what the image or the API is built from, nightly, and on demand — not on every PR, because
a cold build takes most of an hour. The per-PR `ci.yml` checks stay as they were, plus a
stub-based test of the entrypoint's logic.

The GUI acceptance path (a Gazebo window on a real display) remains manual.

## First green run — 2026-09-22

The job passed on its ninth run
([run](https://github.com/konradcinkusz/swarmsim/actions/runs/35796734843)):

- Every drone was on its pad 4 s after reporting.
- The waypoint mission flew and landed in 28 s, each drone within 0.45 m of the end of
  its lane.
- The p95 state age at the API was 0.2 s over 171 samples.
- The aborted formation was on the ground 14 s after the abort.
- The 4-vCPU runner was about half idle after the flight.

Getting there found, run by run, what no test below this layer could have seen:

- **The image.** PX4's installer puts in Gazebo Garden, not the Harmonic that ADR-0001
  chose. It also pip-installs NumPy 2, which breaks Humble's message modules. MAVROS has
  no binary in the Humble apt repository, so the image builds it from its release tags.
- **Heights.** On their pads, drones read up to 2.6 m above the ground. EKF2 fixes its
  origin altitude from wherever its height estimate has drifted by the first GNSS fix.
  Heights are now measured from PX4's home, and SITL uses the barometer as its height
  reference. A drone's first reports also come before the estimator has converged, so
  the smoke waits for the drones to settle.
- **Load.** Each drone's MAVROS loaded every plugin it ships, on a runner shared with
  three PX4 instances and Gazebo, and its time-sync round trip reached 1.3 s. It now
  loads only the six plugins the nodes use (`px4_config.MAVROS_PLUGINS`).
- **The dispatcher never ran.** It kept its publishers in `self._publishers`, where
  `rclpy.node.Node` keeps its own list. It died at start in every run that got as far
  as starting it, so no mission ever reached a drone. The fake rclpy the node tests use kept its books under other
  names, and passed. It now keeps them under rclpy's names, and refuses a node that
  takes one over.

What made these findable was putting each PX4 instance's own view into the job log
(`docker/tests/px4_state.sh`), along with every request a controller made and every
refusal. A red run can be read without downloading anything.

## Amendment — 2026-09-23: PX4's simulated-sensor stall, and the one fault that gets a second flight

On pull request #30 the smoke failed twice running, runs 14 and 15, the same way both
times. drone_3 armed, and at that moment its PX4 instance stopped publishing simulated
GNSS, compass and battery. It lost horizontal position and blind-landed, and PX4 disarmed
it. drone_1 and drone_2 flew the mission and landed at the ends of their lanes.

- **The fault is inside PX4 v1.15.0's SITL.** GNSS, compass and battery come from PX4
  modules (`sensor_gps_sim`, `sensor_mag_sim`, `battery_simulator`) that run on
  periodic HRT timers.
  - On drone_3 they ran for about 4.8 s of simulated time and never again: 485 battery
    cycles, against about 42,000 on the other two drones.
  - gz_bridge's ground truth kept arriving (the attitude was 8 ms old at the end).
  - Modules woken by uORB callbacks or one-shot timers kept running.
  - Nothing this repository sends PX4 reaches those modules. Upstream,
    [PX4-Autopilot#23130](https://github.com/PX4/PX4-Autopilot/issues/23130) reports the
    same loss of GNSS with ten gz vehicles. It is open, with no fix.
- **The mechanism is probably, but not certainly, this:** the posix HRT's `hrt_call_invoke`
  unlocks to run a callout, then re-enters a periodic call without checking whether
  another thread armed that same call meanwhile. A call linked twice into the callout
  queue cuts the calls behind it out of the queue. Confirming that needs a patched PX4
  build flown many times; until then it stays a hypothesis.
- **What the smoke does about it:**
  - A drone that has not climbed a metre 90 s after its mission fails the flight
    (`TAKEOFF_TIMEOUT_S`), instead of at the mission's 420 s timeout.
  - After a failed flight, `docker/tests/px4_sensor_stall.sh` checks every instance.
    Only one whose `sensor_gps` is more than 5 s stale while its `vehicle_status` is
    fresh counts as this fault.
  - Only then is the stack restarted and flown once more, and the job summary and a
    warning say so. Any other failure, or a second failed flight, fails the job.
- **Why a second flight and not a fix:** the fault is PX4's, it has no upstream fix, and
  the retry cannot hide a regression here, because it fires only on a PX4-internal
  signature. It goes when a PX4 version or a patch in `Dockerfile.sim` removes the fault,
  shown by flights rather than argued.
