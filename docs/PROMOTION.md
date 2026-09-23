# Promotion test: from lab project to product

Where `swarmsim` stands in its author's portfolio, and the written test that would move it.
It is written down so that a promotion is a decision taken against evidence, not a drift.
The same discipline the architecture-standards proposals use: a promotion test whose
conditions nobody can check is only a mood.

## Where it is today

**Cluster E (evidence systems), level P3** — a lab project that proves an idea with a
running instrument, next to the portfolio's other simulation-backed systems. It is not a
product (P1). What it has:

- a swarm that flies end to end in simulation: API → ROS 2 → PX4 SITL → Gazebo and back;
- a scenario instrument that runs in anyone's CI (ADR-0008) and a hosted store for its
  runs (ADR-0011);
- a gate that lets an agent plan missions but never fly one without a person (ADR-0009).

What it does not have is anyone outside this repository depending on it.

## The test

Promote to **P1** only when all three hold. Each one says what counts as evidence.

| # | Condition | Evidence that counts | Status (2026-09-22) |
|---|---|---|---|
| 1 | **SITL agrees with L0.** The scenario verdicts L0 gives are the verdicts the real flight stack gives. | The L1 path (ADR-0012: the same YAML flown through the API against PX4 SITL) runs the scenarios it supports, over three seeds, and every one gets the same outcome in L0 and L1. A scenario L1 cannot fly yet is listed, not counted. So is a run that hit PX4's simulated-sensor stall (ADR-0004); it is repeated. | Not met. The SITL smoke flies two missions, not scenario files; L1 does not exist. |
| 2 | **A named design partner.** Someone outside this repository wants to fly their own swarm algorithm through the scenarios. | A person or organisation, named in writing, with a first scenario of theirs run against their `--sut`. Interest is not evidence; a run is. | Not met. |
| 3 | **One shared kernel on `main`.** The estate's reuse is real here, not copied. | One kernel from the estate consumed on `main` by a pinned version instead of this repository's own copy. For example: `authservice` pulled by an image tag rather than built from its git context (ADR-0005's open item), or the confirmation-token store the write gate shares with agent-eval-bench. | Not met. `authservice` has no published image tag; the write gate has its own store. |

## What promotion unlocks

The work that is written down but deliberately not built, because building it before
the test passes would be building for nobody:

- **ADR-0012's orchestrator** — tenant runs on disposable machines, and private-cloud
  delivery for a partner who cannot send their algorithm anywhere.
- **The `swarmsim-sim` deployment** (the P7 row's "first pilot" trigger).
- **Per-tenant storage** for the run store (ADR-0011's ceiling), and tenant claims in
  `authservice` tokens (the P5 row).

## What does not wait for it

- The instrument itself: scenarios, mutation adequacy, the Action.
- The SITL smoke, and ADR-0013's move to ROS 2 Jazzy. That one waits on a date, not on
  the test.
- `swarmsim-api`'s deployment (ADR-0011). It is cheap enough to stand up as the
  evaluation path a design partner would try first.

When a condition's status changes, change it here in the same pull request as the evidence.
