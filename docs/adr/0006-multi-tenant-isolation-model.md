# ADR-0006: Multi-tenant isolation model for hosted swarm testing

## Status

Accepted

## Context

Pillar 3 of the swarm-testing-as-a-service product ("not an add-on, a condition of
sale") is hard per-client isolation: a client's swarm-coordination algorithm is their
IP, and it is exactly the thing `swarm_coordination`'s node wrappers exist to run —
client-supplied `formation.py`/`waypoints.py`/`trajectory.py`-shaped code executed
against the sim, not just client data read through an API. A defense or agri client's
objection is not "your RBAC might have a bug"; it is "my code must never share a
runtime with anyone else's," and no amount of row-level or endpoint-level access control
answers that objection, because the thing being isolated is *code execution*, not just
data.

Today's architecture has no tenant concept to isolate in the first place: ADR-0002 set
up `docker/docker-compose.yml` as one composition root, run once, standing up one `sim`
service and one shared `SwarmApi.Api` instance for whoever is using the stack. Fixed
host ports (`9090` for rosbridge, `8080` for the API, `14550-14559` for MAVLink) and a
single `swarmsim-net` network assume exactly one instance of the whole stack exists at
a time on a given host.

## Decision

Ephemeral, per-tenant-per-run container instantiation — not a shared instance with
per-tenant RBAC/data isolation.

The shared-instance option is cheaper to build (it is close to today's architecture:
add a tenant column, an auth middleware, and scope queries by it) but it does not
actually satisfy Pillar 3: it still means executing multiple tenants' coordination code
in containers on shared infrastructure, gated by application-level checks that a
sufficiently determined or merely buggy neighbor tenant can undermine. For a client
whose stated posture is "we will not send our algorithm to shared infrastructure," that
is not a smaller version of what they asked for — it is a different, weaker guarantee
they explicitly ruled out. Selling it as isolation would be a claim this repo cannot
back up the way P8's "every optional dependency degrades, visibly" and P13's testability
principle ask every other claim here to be backed up.

Concretely, this changes `docker/docker-compose.yml`'s role from ADR-0002's "the
composition root a developer runs once" to a **template** instantiated once per active
tenant run:

- `docker compose -f docker/docker-compose.yml -p tenant-<tenant-id>-<run-id> up` — the
  `-p` project name is what gives each run its own container namespace, its own
  `tenant-<tenant-id>-<run-id>_swarmsim-net` network, and its own volumes; the compose
  file's service definitions (`sim`, `api`) do not change.
- Fixed host port publishing (`9090:9090`, `8080:8080`, `14550-14559:...`) cannot stay —
  two concurrent tenant stacks would collide on the same host. Ports move to
  container-internal only (no `ports:` mapping to the host at all); the only thing
  reachable from outside a tenant's own network is a per-run ingress the orchestrator
  issues, keyed to that tenant's run.
- Teardown (`docker compose -p tenant-<tenant-id>-<run-id> down -v`) after the run
  completes or times out is what actually delivers the isolation guarantee: no tenant's
  containers, volumes, or network segment outlive their own run to be inspectable by the
  next tenant's stack coming up on the same host.
- A new component this repo does not have yet — an orchestrator that creates and tears
  down these per-tenant stacks on request — becomes a **third** composition root sitting
  above the two ADR-0002 established (`docker/docker-compose.yml` for the sim layer,
  plain `dotnet run` for the single .NET service). ADR-0002's reasoning for keeping the
  sim stack outside any AppHost (GUI/build-time cost) still holds; what changes is that
  "the sim stack" is no longer a singleton a developer brings up by hand — it is a shape
  the orchestrator instantiates N times. Designing that orchestrator is out of scope for
  this ADR; it is the recorded consequence, not the decision.

Interaction with the auth-approach ADR: that ADR owns *authenticating* a request and
producing a tenant identity; this ADR owns what happens once that identity exists — it
is the opaque `<tenant-id>` used to name and network-isolate that tenant's stack. The
orchestrator trusts the tenant identity the auth-approach ADR's mechanism hands it and
does not re-derive it. Neither ADR is meaningful without the other: per-tenant
containers with no authenticated tenant identity routing requests to them isolate
nothing, and an authenticated tenant identity with a shared backend behind it is the
shared-instance option this ADR rejects.

## Consequences

- No implementation lands from this issue (per its acceptance criteria) — the
  orchestrator, per-run compose invocation, and ingress routing are new infrastructure
  work, unscheduled against the current milestone plan in the root README, and tracked
  as follow-up rather than built here.
- Every tenant run now pays PX4 SITL/Gazebo container start-up cost that a long-lived
  shared stack would only pay once (ADR-0001 already documents the first-build cost as
  "normal, not a bug"; this makes *steady-state per-run* cost matter too, not just
  first-build cost). A pre-built, cached `swarmsim/sim` image (already the case per
  ADR-0001) keeps this to container start latency, not a PX4 rebuild, but it is still
  slower than hitting an always-on API.
- Host capacity for concurrent GPU-capable stacks becomes a real scaling constraint —
  N concurrent tenant runs means N concurrent GPU/X11-passthrough containers (ADR-0001's
  `HEADLESS` toggle helps for tenants that don't need the GUI acceptance path, but SITL +
  Gazebo + ROS 2 per run is not free even headless).
- `docs/adr/0003-rosbridge-degrade-pattern.md`'s pattern is unchanged in kind but its
  config value is now per-run: `RosBridge:Url` becomes
  `ws://sim-<tenant-id>-<run-id>:9090` (the compose project's internal DNS name) instead
  of the fixed `ws://sim:9090`, generated by the orchestrator when it starts a tenant's
  `api` instance rather than hardcoded in a checked-in compose file.
- CI's existing `docker compose -f docker/docker-compose.yml config -q` check
  (ADR-0004) still validates the template's syntax and service graph exactly as before —
  it validates one instantiation of the shape, which is all it ever needs to do; the
  orchestrator's per-run parameterization is new surface CI does not cover yet and would
  need its own test strategy when built.
- **Recorded trigger to revisit:** the day the orchestrator is designed, it gets its own
  ADR — this one fixes the isolation *unit* (a full per-tenant-per-run stack, torn down
  after use) and the ingress rule (no published host ports, no direct network path
  between tenants), not the orchestrator's implementation.

Worked example: `docker/docker-compose.yml`, `docs/adr/0002-composition-root-split.md`,
`docs/adr/0003-rosbridge-degrade-pattern.md`.
