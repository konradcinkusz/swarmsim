# ADR-0012: A tenant run is a disposable machine; the orchestrator is an interface with three platforms

## Status

Accepted as a design (2026-09-22). **Not built**: building it waits on the promotion test
in [`docs/PROMOTION.md`](../PROMOTION.md). Follows ADR-0006, which fixed the isolation
unit and left the orchestrator to "its own ADR — the day it is designed". This is that
ADR. Amends ADR-0007's `swarmsim-sim` unit: Fly.io GPU Machines no longer exist.

## Context

ADR-0006 decided *what* is isolated: a whole stack per tenant per run, with no published
host ports and no network path between tenants, torn down after the run. It did not
decide what creates and destroys those stacks. Three facts have changed since:

- **Fly.io ended GPU Machines.** They were deprecated as of 31 July 2026 and unavailable
  from 1 August 2026, according to Fly's own community announcement ("Fly.io GPUs will be
  deprecated as of July 31, 2026"). ADR-0007 put `swarmsim-sim` on them.
- **The simulator does not need a GPU.** The SITL smoke runs Gazebo headless, three PX4
  instances, MAVROS, the ROS 2 nodes, rosbridge and the API on a stock 4-vCPU GitHub
  runner with no GPU at all. The CPU snapshot taken after the flight shows the machine
  about half idle (`top` in the job log). Only the optional Gazebo GUI wants a GPU, and
  tenant runs are headless.
- **What a customer pays for is running *their* swarm** (ADR-0008's `--sut`). Their
  algorithm is the thing that must never share a runtime with anyone else's. The
  scenarios, the reference swarm and the run store are not.

## Decision

**A tenant run is one disposable machine: the simulation image with the tenant's software
added. An orchestrator creates it for one run and destroys it after; nothing about the run
outlives it except the report it hands back.**

- **The run's lifecycle:**
  1. **Requested**: by a token that carries a tenant claim. There is no tenant without
     one (ADR-0006: an unauthenticated tenant id isolates nothing).
  2. **Provisioning**: one machine from `swarmsim-sim:<version>` plus the tenant's layer,
     in the tenant's own private network, with no public service.
  3. **Running**: the scenario files are flown through the run's own API instance against
     the run's own PX4 and Gazebo. This is the L1 path ADR-0008 left open — the same
     YAML, flown for real.
  4. **Collecting**: the report goes to the run store (ADR-0011) under the tenant.
     Traces and PX4 ULogs go to the tenant, not to us.
  5. **Destroyed**: the machine and its disk. A hard TTL per run, and a reaper that
     destroys any run machine older than it. A crashed orchestrator must not leave a
     tenant's code running (P8's spirit: the failure mode is "stopped", never "leaked").
- **The orchestrator is an interface, `IRunPlatform`, with a registration per platform
  (P10), not a Fly client with branches:**
  - **Fly Machines**, for the hosted product. One app per tenant, created in its own custom
    private network (`fly apps create --network`), so 6PN does not connect one tenant's
    machines to another's. CPU Machines (`performance-4x`, 8 GB) — the size the smoke's
    headroom suggests for three to five drones, to be measured, not trusted.
  - **Docker Compose**, for a laptop, CI, and the evaluation path. `docker compose -p
    tenant-<id>-<run>` is ADR-0006's own template.
  - **The customer's cloud** — private-cloud delivery
    (architecture-standards PRIVATE-CLOUD-DELIVERY): the vendor pushes the images into
    the customer's registry and stops. The customer runs the orchestrator and the stacks
    with the IaC they are given, so a client who will not send their algorithm anywhere
    never has to. Same code, no fork; what differs is the platform registration and who
    holds the credentials.
- **The free, local path stays free and local.** The scenario Action (ADR-0008) needs no
  orchestrator and no account. The orchestrator is for L1 runs a customer cannot or will
  not host themselves.

## Consequences

- Nothing is built. The promotion test says when: a named design partner who wants to fly
  their own algorithm, an L0 verdict that SITL confirms, and one shared kernel used on
  main. Until then this ADR is the design that work starts from, not a backlog.
- ADR-0007's `swarmsim-sim` on GPU Machines is replaced by CPU Machines, or by whatever the
  customer runs. The P7 `swarmsim-sim` row keeps its "first pilot" trigger, with the reason
  corrected.
- Tenant identity becomes a hard prerequisite, not a follow-up. `authservice` must issue a
  tenant claim (ADR-0005's P5 row lists per-tenant claims as a trigger), and the run store
  must key runs by tenant before a second tenant exists. ADR-0011's single-machine file
  store ends there.
- A run pays machine start plus Gazebo and PX4 boot every time. That is tens of seconds
  from the cached image, and the estimators settle about 4 s after the drones report (the
  smoke measures both). It is billed per second and bounded by the TTL. It is the cost of
  the isolation ADR-0006 chose over a shared stack, and it is why L0 stays the every-push
  tier.
- PX4 v1.15's SITL can lose one drone's simulated sensors at arming (ADR-0004, 2026-09-23;
  PX4-Autopilot#23130). It happened on two of the smoke's first six green-era flights. A
  tenant's L1 verdict must not be decided by it. Until a PX4 patch or version removes it,
  the orchestrator checks every run with `docker/tests/px4_sensor_stall.sh` and repeats a
  run that hit it, instead of reporting it against the tenant's swarm.

Worked example: none yet — `docker/docker-compose.yml` (the per-run template),
`.github/workflows/sim-smoke.yml` (one run, on a CPU-only runner).
