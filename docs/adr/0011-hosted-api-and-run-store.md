# ADR-0011: The hosted API stores and compares scenario runs, and never runs Open

## Status

Accepted (2026-09-22). Acts on ADR-0007's `swarmsim-api` unit; closes the P7 `swarmsim-api`
row's "no `fly.toml`" and the P12 row's "no deploy job".

## Context

ADR-0007 split deployment into two Fly.io units and gave the cheap one — `swarmsim-api`, no
GPU — the trigger "the scenario library lands". It landed, and then ADR-0008 changed what
it is: the scenarios now run in the caller's own CI, as a GitHub Action, and a verdict never
needs a server. What a server can add is **memory**:
- what the suite said on the last commit;
- which scenario regressed between two runs;
- which mutant started surviving.

That is the open-core line the scenario study points at. Running is free and local;
remembering and comparing is the hosted part.

Two things had to be true before anything went on a public URL:

- **It must not run Open.** ADR-0009 made Open mode a rule for one machine only: in Open
  mode anyone who can reach the API can approve a plan and fly it. Today the only thing
  standing between `Auth:Authority` being forgotten and an Open public API was that
  nobody forgot.
- **A stored run must survive a stop.** The app scales to zero; memory does not survive
  that.

## Decision

- **`POST /api/scenario-runs` stores the runner's JSON report** — whole, as the runner
  wrote it.
  - Its shape is a contract: `contracts/scenario/report.v1.schema.json`, `version: 1`.
    The runner writes it; the API reads it. Both test suites hold themselves to
    `contracts/scenario/examples/report.json`, and a test fails if that example drifts
    from what the runner writes today (P11).
  - A report outside the contract is a 400 listing every reason.
- **The other endpoints:**
  - `GET /api/scenario-runs` lists runs.
  - `GET /api/scenario-runs/{id}` reads one.
  - `GET /api/scenario-runs/compare?base=&head=` says, per scenario:
    - regressed (met its expectation, now does not), fixed, changed, unchanged, added or
      removed;
    - each assertion's measured value averaged over the seeds, in both runs, and the
      delta;
    - which mutants newly survive, and which no longer do.
- **A run carries someone's scenarios, so reading one needs a token** in Enforced mode — a
  new class in [API-SURFACE.md](../architecture/API-SURFACE.md), `private-read`. The swarm
  reads stay open as before. Ingest is a `record`: it stores, nothing flies.
- **The runner uploads with `--upload API_URL`** (token from `SWARMSIM_API_TOKEN`); the
  Action has `upload-url`, `upload-token` and `upload-label` inputs.
  - The upload carries an `Idempotency-Key`. A timed-out attempt is retried once under
    the same key, and after that the run is reported as "may or may not be stored".
  - A failed upload is a warning and **never changes the verdict**: the scenarios decided
    it where they ran. Nothing leaves the job unless `upload-url` is set.
- **Where runs are kept:** one JSON file per run under `ScenarioRuns:Directory` — on Fly.io,
  a 1 GB volume.
  - A run is on disk before it is acknowledged: a temporary file, then an atomic rename.
  - The directory is indexed at start, newest first, up to `ScenarioRuns:MaxRuns` (1000);
    past that, the oldest file is deleted.
  - Unset: runs are kept in memory, logged and reported by `/health`
    (`scenarioRuns: InMemory`). Set but not writable: startup stops.
  - This is not a database, on purpose. It is one aggregate type — immutable documents,
    read one at a time, by one machine. The P3/P4 row records the trigger for Postgres.
- **`Auth:Required`** stops startup when no authority is configured. The Fly config sets it,
  so `swarmsim-api` either runs Enforced or does not run. The authority comes from the
  `SWARM_AUTH_AUTHORITY` repository variable, and the deploy fails without it
  (`flyio/SECRETS.md`).
- **Deploying:** `flyio/swarmsim-api.fly.toml` and `.github/workflows/flyio.yml`, following
  FLY-IO-DEPLOYMENT.
  - A `v*` tag runs the tests, then detects changes against the previous tag; the app is
    always selected if it does not exist yet.
  - The image is built once and pushed to `registry.fly.io`, then deployed with one
    machine and its volume.
  - After the deploy, the workflow checks that `/health` says `Enforced` and `File` — the
    two things a green platform health check cannot see.
  - Without `FLY_API_TOKEN` the workflow deploys nothing and says so.
- **The API image starts as root only to hand the volume to its `app` user**, then drops to
  it with `setpriv` (`backend/docker-entrypoint.sh`). Fly mounts volumes owned by root, and
  this is the official Postgres image's pattern.
- **No `RosBridge__Url` in the hosted config.** It runs the simulated swarm, labelled
  `Simulated`, as the dashboard's demo. Flying a tenant's swarm is ADR-0012's unit, not
  this one.

## Consequences

- Nothing is deployed until someone creates a Fly token and names an `authservice`. The
  workflow is written, linted and gated; its first real run is the one-time setup in
  `flyio/SECRETS.md`. The P7 and P12 rows are narrowed to exactly that, not deleted.
- The run store's ceiling is the volume: one machine, one region, no replication beyond
  Fly's daily volume snapshots. Enough for one team's history; not for many tenants.
  ADR-0012's per-tenant storage is where that changes.
- The API image's process runs as `app`, but its container starts as root. The compliance
  checklist's P6 row says so, rather than keeping "USER app" true in letter only.
- Comparison is by scenario name, and by assertion name and occurrence, so renaming a
  scenario reads as removed + added. That is accepted: a renamed scenario *is* a different
  claim until someone says otherwise.

Worked example: `backend/src/SwarmApi.Application/ScenarioRuns.cs`,
`backend/src/SwarmApi.Infrastructure/ScenarioRunStores.cs`,
`swarm_coordination/swarm_coordination/scenarios/upload.py`,
`backend/tests/SwarmApi.Api.Tests/ScenarioRunEndpointTests.cs`.
