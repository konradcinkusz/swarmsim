# ADR-0007: Deployment target: Fly.io vs Azure

## Status

Accepted

## Context

`docs/architecture/DEVIATIONS.md`'s P7 row already names Fly.io as this repo's
constitutional default deployment target and records that nothing is deployed yet
("no `fly.toml`, no deployed environment... deployment credentials were never
provided or requested"), with trigger "first pilot with a real operator." The P12 row
(tag-driven CI/CD, ordered deploy) is deferred for the same reason: there is nothing to
deploy to yet. Neither row is an accident — `docs/architecture/README.md` notes the
constitution itself "was extracted from .NET Aspire SaaS products deployed to
Fly.io/Azure," so both platforms are within the standard's own precedent; P7 already
picked one of the two.

Separately, an earlier project analysis outside this repo ("Plan implementacji")
specified Azure for the backend. That analysis predates this repo's adoption of
`architecture-standards` and P7's Fly.io default, and the two have never been
reconciled in writing. This ADR is that reconciliation.

Two runtime shapes exist under this one repo, and they do not cost the same to run:

- `SwarmApi.Api` plus the scenario-testing product path — the pure-Python scenario
  library under `swarm_coordination/swarm_coordination/scenarios/` (issue #12).
  Confirmed by inspection: none of those modules import `rclpy` or anything else from
  the ROS 2 apt distro (root README's own split of "pure-logic" vs. ROS-dependent
  modules already documents this). It needs no GPU, no X11, no Gazebo process at
  runtime — a scenario run is a plain Python function call.
- The full Gazebo + PX4 SITL + ROS 2 stack (`docker/Dockerfile.sim`, ADR-0001) — GPU/X11
  dependent, a tens-of-minutes image build (ADR-0004), and per the multi-tenant
  isolation ADR, headed toward running as ephemeral, per-tenant-per-run container
  instances that are created and torn down around a single client's test session rather
  than one long-lived deployment.

Bundling both under one deployment target's cost envelope means the cheap path's
economics are dictated by the expensive path's requirements. That is the split this ADR
has to rule on, not just "which cloud."

## Decision

**Fly.io, not Azure, for everything in this repo — split into two separate Fly
deployment units, not one.**

Why Fly.io over Azure, for both:

- P7 already defaults to it and nothing in this repo's actual constraints argues for
  spending the reconciliation effort to move off that default onto the out-of-repo
  analysis's Azure recommendation instead. The Azure analysis is not wrong on its own
  terms, it is simply not this repo's terms.
- Fly Machines (create/start/stop/destroy a VM by a single API call, billed to the
  second, true scale-to-zero) is close to a direct infrastructure match for the
  multi-tenant isolation ADR's ephemeral per-tenant-per-run unit: that ADR's
  `docker compose -p tenant-<id>-<run> up` / `down -v` lifecycle maps onto a Fly Machine
  create/destroy call almost directly. Azure's nearest equivalents (Container Instances,
  an AKS node pool, a VM Scale Set) all require assembling that same start-cheap,
  stop-completely behavior out of lower-level primitives Fly ships as the product
  itself — extra orchestration surface this repo would own and maintain for no
  functional gain.
- At zero revenue, idle cost is the cost that matters most, and it is where the two
  diverge furthest: Fly's per-second billing with scale-to-zero (CPU and GPU Machines
  alike) means a Machine not currently serving a request or a tenant run costs nothing.
  Azure's GPU-capable compute (the NC-series family) is VM/node-pool shaped, oriented
  around staying warm to avoid cold-start penalties — the opposite of what an
  intermittent, pre-revenue, per-tenant-run workload wants to pay for.

Why two deployment units instead of one:

1. **`swarmsim-api`** (Fly.io app, shared-cpu Machines) — `SwarmApi.Api` plus the
   scenario-testing product path. No GPU, no Gazebo, scale-to-zero when idle. Its cost
   floor is low enough that it does not need to wait on the same precondition as the GPU
   stack below; it is cheap enough to justify standing up once issue #12's scenario
   library has something worth demoing, well before "first pilot with a real operator"
   is reached.
2. **`swarmsim-sim`** (Fly.io GPU Machines) — the Gazebo/PX4/ROS 2 stack, instantiated
   per-tenant-per-run per the multi-tenant isolation ADR, never as a standing
   deployment. This stays behind P7's existing "first pilot with a real operator"
   trigger: GPU-seconds are real money, and nothing in this repo yet generates a run
   that isn't a developer's own manual verification (ADR-0004).

Same platform for both keeps one operational model (one Machines API, one set of Fly
org/account conventions) even though they are two separately deployed, separately
triggered units — that is the "explicit, justified split" this decision commits to,
not a platform split and not an "it depends."

## Consequences

- This supersedes the out-of-repo Azure analysis for the backend. If Azure needs to be
  revisited (an enterprise client's data-residency requirement is the plausible future
  trigger), that is a new ADR that reopens this one — not a silent fallback to the
  earlier analysis.
- `docs/architecture/DEVIATIONS.md`'s P7/P12 rows are not closed by this ADR — there is
  still no `fly.toml` and no deploy job. What this ADR fixes is what those rows'
  eventual close-out targets: when `swarmsim-api`'s `fly.toml` is written, it targets
  Fly.io, on its own trigger (issue #12 landing), separately from `swarmsim-sim`'s,
  which keeps the "first pilot" trigger P7 already records. Splitting the P7 row itself
  into two rows with two triggers is follow-up for whoever next edits
  `DEVIATIONS.md`, not done here.
- Two Fly apps means two `fly.toml`s, two secret sets, and eventually two release
  paths under P12's tag-driven CI/CD, rather than one — accepted, because the
  alternative (one deployment gated on the GPU stack's precondition) is what this ADR
  is rejecting.
- Fly.io GPU Machine region/SKU availability becomes a constraint the multi-tenant
  isolation ADR's orchestrator has to design around specifically (queueing or
  region-shifting a tenant run when Fly's GPU capacity in a region is saturated),
  rather than a generic "some cloud has GPUs somewhere" assumption.
- No `fly.toml` is added here — this is a decision document. The next actionable step
  is writing `swarmsim-api`'s `fly.toml` when issue #12 lands; `swarmsim-sim`'s deploy
  path waits on the multi-tenant isolation ADR's orchestrator being built and P7's
  existing trigger firing.

Worked example: `docker/docker-compose.yml`,
`swarm_coordination/swarm_coordination/scenarios/`,
`docs/adr/0004-ci-scope-for-simulation-stack.md`.
