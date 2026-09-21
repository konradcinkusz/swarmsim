# Open deviations

Per [`00-REFERENCE-ARCHITECTURE.md` §3a](https://github.com/konradcinkusz/architecture-standards/blob/main/docs/architecture/00-REFERENCE-ARCHITECTURE.md#3a-known-open-deviations):
an unacknowledged gap from the constitution is drift; an acknowledged one is a decision.
This table is that acknowledgment. When a row is fixed, it is deleted, not marked done.

| Principle | Deviation | Since | Reasoning / trigger to close |
|---|---|---|---|
| P1 (AppHost is the composition root) | No .NET Aspire AppHost. `SwarmApi.Api` is a single ASP.NET Core project; the development composition root is `docker/docker-compose.yml`. | M3 (this phase) | See [ADR-0002](../adr/0002-composition-root-split.md). Trigger: the LLM mission layer (M5) adds a second .NET service — that is the point an AppHost starts paying for itself. |
| P7 (Fly.io is the deployment target) | No `fly.toml`, no deployed environment. `SwarmApi.Api` is developed and tested locally / in CI only. | M3 (this phase) | This phase has no users and no production traffic; deployment credentials were never provided or requested. Trigger: first pilot with a real operator, per the source analysis's own scoping ("poza zakresem tej fazy: ... certyfikacja"). |
| P5 (JWT / asymmetric signing) | `SwarmApi.Api` has no authentication. Every endpoint is open. | M3 (this phase) | Single-operator local/dev tool with no deployed, internet-reachable instance; no user identity exists yet to authenticate. Trigger: the first deployment reachable outside localhost, or the LLM layer (M5) introducing a caller identity worth distinguishing. |
| P15 (OTLP observability) | No OpenTelemetry exporter wired. `SwarmApi.ServiceDefaults` exposes `/health` and `/alive` only. | M3 (this phase) | No collector endpoint exists to export to yet, and P8's "visible degradation" is met more cheaply here by the `/health` payload naming the bridge mode (`Connected` / `Simulated`). Trigger: first deployed environment with an OTLP collector. |
| P12 (tag-driven CI/CD, change detection, ordered deploy) | CI builds and tests on every push/PR; there is no deploy job. | M3 (this phase) | Follows directly from the P7 deviation above — there is nothing to deploy to yet. Trigger: same as P7. |
| P3 / P4 (service owns its database, `MigrateAsync`) | `SwarmApi.Api` is stateless; swarm state lives in memory (real: rosbridge-fed; fallback: simulated engine) and missions are not persisted across restarts. | M3 (this phase) | Outside the rule, not an exception to it (constitution P4 note): there is no entity model and no schema to migrate. A mission history / audit log is a plausible M5+ requirement, not a current acceptance criterion. Trigger: a requirement to recall a mission after a restart. |
| P13 (E2E layer / Playwright) | No end-to-end browser suite. The dashboard is covered by manual verification only (documented in the root README's M4 section). | M4 (this phase) | No user-facing flow exists yet beyond a single read-only polling page; a Playwright suite for one page is cost without signal (TESTING-STRATEGY.md §1's charter). Trigger: the dashboard gains an interactive flow (e.g., submitting a mission from the UI). |

Everything not listed here is met as stated in `docs/architecture/README.md`'s
compliance checklist.
