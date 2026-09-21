## What changed and why

<!-- The reasoning, not just the diff. What did this change accomplish, and why this
approach over the alternatives? -->

## Milestone

<!-- Which milestone from docs/architecture/00-REFERENCE-ARCHITECTURE.md / the
foundational-phase plan does this move forward? M0 / M1 / M2 / M3 / M4 -->

## Acceptance criteria touched

<!-- Copy the relevant criteria from the milestone table and check them off with
evidence (test name, command output, screenshot). -->

- [ ]

## Test plan

<!-- What was run, and what a reviewer can re-run to verify. -->

## Compliance checklist

- [ ] Tests added/updated at the layer that holds the logic (P13)
- [ ] No secret literal in source, config, or comment (P5) — scanner is green
- [ ] Optional/external dependencies degrade rather than fail startup, where applicable (P8)
- [ ] Documentation updated if behavior, setup, or architecture changed (P14)
- [ ] `docs/architecture/DEVIATIONS.md` updated if this introduces or resolves a deviation
