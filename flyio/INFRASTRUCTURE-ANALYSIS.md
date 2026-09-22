# Fly.io: topology, sizing and cost

The reasoning P7 asks to be written down, per deployed unit (architecture-standards
FLY-IO-DEPLOYMENT §13). ADR-0007 chose the platform and split the two units; ADR-0011
decided what the hosted API does; ADR-0012 decides how simulator runs would be hosted.

## Units

| Unit | Deployed | Shape | Why |
|---|---|---|---|
| `swarmsim-api` | from a `v*` tag, `.github/workflows/flyio.yml` | one stateless-image HTTP app with one volume, `shared-cpu-1x`, 512 MB, scale to zero | The run store (scenario reports, docs/adr/0011), the agent write gate and the dashboard over the simulated swarm. Nobody calls it in-request, so `min_machines_running = 0` and the proxy wakes it; a cold start costs a first request a few seconds. |
| `swarmsim-sim` | not deployed | per tenant run, never standing (docs/adr/0012) | Gazebo + PX4 SITL + ROS 2. |

## Why one machine and a volume, not Postgres

A scenario run is an immutable JSON document, written once and read one at a time. One
file per run on a 1 GB volume holds tens of thousands of runs at a few kilobytes each —
`ScenarioRuns__MaxRuns` (default 1000) caps it well below that. A Postgres app would add
a second unit, a second bill and a migration story for no query this store makes. The
cost: a volume belongs to one machine in one region, so the API cannot scale out, and the
volume is not replicated — Fly snapshots volumes daily, and that is the backup. The
trigger to move to Postgres is recorded in `docs/architecture/DEVIATIONS.md` (P3/P4): a
second machine, or per-tenant storage.

## Cost, at zero revenue

- **Compute:** billed per second while a machine runs. Stopped between requests, so an
  idle month costs close to nothing; a machine that ran all month on `shared-cpu-1x`
  512 MB would still be a few dollars.
- **Volume:** billed per GB-month whether the machine runs or not — 1 GB is the fixed floor.
- **Egress and the dedicated IPv4:** not used; the shared IPv4 and IPv6 are free.

## Not built yet, on purpose

- Scale and destroy workflows (FLY-IO-DEPLOYMENT §12): one app, one machine, one volume —
  `flyctl` by hand is proportionate until there is a second unit.
- An OTLP collector: `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, so telemetry is `Off`
  (docs/adr/0010) until one exists; setting it as a Fly secret turns export on with no
  code change.
