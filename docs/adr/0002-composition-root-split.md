# ADR-0002: Two composition roots, not one Aspire AppHost

## Status

Accepted

## Context

Constitution P1: "One Aspire `AppHost` project declares every resource the system
needs... A developer clones the repository and runs one command." The reference systems
this was extracted from are all-.NET: every resource an AppHost orchestrates (a database,
a cache, a project, a Next.js frontend) either has a first-class Aspire integration or is
a container Aspire can start and health-check generically.

The simulation stack here does not fit that shape:

- It needs privileged/device access and X11 (or Wayland) socket passthrough for GUI
  rendering, which Aspire's container model does not express.
- Its image takes tens of minutes to build the first time (PX4 compiled from source);
  treating it as a normal Aspire-managed container conflates "orchestrate" with "build",
  and a `dotnet run` on the AppHost is not where a contributor expects a 30-minute wait.
- It is one stack shared by every future .NET service (this phase has exactly one:
  `SwarmApi.Api`), not a per-service dependency an AppHost's per-project graph models.

## Decision

Two composition roots, each for the layer it actually composes:

- **`docker/docker-compose.yml`** — ROS 2 + PX4 SITL + Gazebo, with a `HEADLESS`
  environment toggle for GPU-less environments (documented risk in the source analysis).
  This is what a contributor runs to get the simulation itself up.
- **Plain `dotnet run --project backend/src/SwarmApi.Api`** — no Aspire AppHost. A single
  ASP.NET Core project has no second resource to compose; an AppHost around one project
  is ceremony with no payoff yet.

This is a deviation from P1's letter (recorded in `docs/architecture/DEVIATIONS.md`), not
from its intent: the point of P1 is that setup is one command per layer a contributor
actually needs to bring up, and it stays that way here.

## Consequences

- No `SwarmApi.AppHost` project exists yet. `SwarmApi.ServiceDefaults` (P2) is still
  built now, ahead of needing it for orchestration, because it is what makes the *next*
  service cheap to add correctly (`/health`, `/alive`, CORS) — it does not depend on an
  AppHost existing.
- **Recorded trigger to revisit:** the day a second .NET service is added (the M5 LLM
  mission-translation layer is the planned one), stand up `SwarmApi.AppHost` referencing
  both projects. At that point the AppHost becomes the thing P1 describes: a real graph
  with `WithReference`/`WaitFor` edges, not a wrapper around a single node.
- The simulation stack stays outside any future AppHost's graph regardless (same
  GUI/build-time reasoning above); the AppHost would compose the .NET services only, with
  `SwarmApi.Api` pointed at the independently-running compose stack via configuration
  (`RosBridge:Url`) — the two composition roots talk to each other over a URL, never over
  a shared orchestrator.

Worked example: `docker/docker-compose.yml`, `backend/src/SwarmApi.ServiceDefaults/`.
