# ADR-0005: Auth approach for the first internet-reachable SwarmApi deployment

## Status

Accepted

## Context

`docs/architecture/DEVIATIONS.md`'s P5 row records today's state plainly: every
`SwarmApi.Api` endpoint is open, with the trigger to close it being "the first
deployment reachable outside localhost, or M5 introducing a caller identity worth
distinguishing." `Program.cs` bears this out — `AddSwarmBridgeAsync` is the only
startup decision made before `builder.Build()`; there is no `AddAuthentication`,
no `[Authorize]`, nothing between a request and an endpoint handler but CORS and
static-file serving.

That trigger is no longer hypothetical. Three interfaces now exist or are being built
against this same API: the REST API itself (consumed today by the same-origin
dashboard in `wwwroot`), a GitHub Action (issue #19 — a CI job POSTing a mission and
polling swarm state, unattended, non-interactive), and an MCP server (issue #20 — a
thin tool wrapper a local AI-client process calls against the same two endpoints).
None of the three is "a person logging in": one is a browser operated by whoever
deployed this instance, one is a CI job, one is a local process. There is also still
no user/entity model anywhere in this codebase — `docs/architecture/DEVIATIONS.md`'s
P3/P4 row is explicit that `SwarmApi.Api` is stateless with no database — so any
mechanism that presupposes a subject to issue claims *to* is inventing infrastructure
this phase has no other use for.

The root README's "Packages and dependencies" section records that runtime code ships
**zero third-party NuGet packages** today; whatever this ADR decides has to either hold
that line or say explicitly why it doesn't.

## Decision

**API keys, not JWT, checked by one piece of ASP.NET Core middleware inside
`SwarmApi.Api`, shared by all three interfaces.**

- **Mechanism.** Architecture-standards' P5 names JWT/asymmetric signing, but JWT's
  value is per-*user* claims, expiry, and revocation without a shared secret — it needs
  a subject. This system's three callers are pre-provisioned integrations (a browser
  belonging to the instance's operator, a CI job, a local MCP process), not
  interactively-authenticated people; that is exactly the shape API keys are for, and
  is the same pattern issue #19 itself names (Codecov/Snyk: a static token an Action
  passes as a secret). Standing up JWT here would mean building a signing-key story, an
  issuance endpoint, and a subject/claims model with no current requirement driving
  their shape — cost with no payoff yet. This is a deliberate deviation from P5's
  letter, same reasoning shape as ADR-0002's deviation from P1: the constitution's
  prescription assumes human end-users; this phase's callers aren't. **Trigger to add
  JWT on top of (not instead of) API keys:** a real human-login flow — a hosted,
  multi-tenant dashboard with individual accounts, which is the same M5-shaped trigger
  DEVIATIONS.md's P5 row already names.
- **Enforcement point: middleware in `SwarmApi.Api`, not a separate gateway.** No
  deployment target exists yet to run a second process on (P7's own deviation row), and
  a gateway would be a third composition root for zero-payoff ceremony — the same
  argument ADR-0002 already made against an AppHost nobody needs yet. A custom
  `AuthenticationHandler<ApiKeyAuthenticationSchemeOptions>` registered via
  `AddAuthentication().AddScheme<...>()` lives entirely in
  `Microsoft.AspNetCore.Authentication.Abstractions`, already reachable through the
  `Microsoft.AspNetCore.App` `FrameworkReference` every project here already has — no
  new NuGet package, holding the README's zero-third-party-package line. Key storage
  sits behind an `IApiKeyStore` in `SwarmApi.Application` (P10: interface + DI, no base
  class — the same rule `ISwarmBridge` follows), with a `ConfigurationApiKeyStore` in
  `SwarmApi.Infrastructure` reading an `ApiKeys` section via `IOptions<ApiKeyOptions>` —
  the exact shape `RosBridgeOptions` + `AddSwarmBridgeAsync` already establish. Keys are
  stored and compared as SHA-256 hashes (`CryptographicOperations.FixedTimeEquals`),
  never plaintext, all BCL.
- **Sharing across REST / Action / MCP: one layer, one key per integration.** The
  Action and the MCP server are not separate backends to secure — both are HTTP callers
  of the same `POST /api/missions` / `GET /api/swarm/state` endpoints the dashboard
  already calls. So there is one `[Authorize]`-gated set of endpoints and one
  validation path, not three. Each *integration* gets its own named key
  (`swk_action_…`, `swk_mcp_…`, `swk_dash_…` prefixes, matching the Stripe/GitHub
  convention of a prefix that says what leaked without decoding it) so a compromised
  key — e.g. an Action secret exposed in a public workflow log — is revoked alone,
  without rotating the other two. The dashboard is the one caller with a human behind
  it rather than a pre-provisioned integration; with no login system to issue it a key
  through, its key is entered once into a small prompt in the existing `wwwroot` JS and
  cached in `sessionStorage`, sent as the same `X-Api-Key` header the other two use — no
  new backend surface, and it is exactly the piece that gets deleted the day a real
  login flow (JWT, per the trigger above) replaces it. `/health` and `/alive` stay
  unauthenticated — orchestrator/host probes need to reach them pre-auth, and per
  ADR-0003 they already expose nothing beyond bridge mode.

## Consequences

- No self-service key issuance or rotation exists: provisioning or revoking a key today
  means an operator edits the `ApiKeys` configuration/secret and restarts. That is a
  real gap the day this has external paying users, not before — it is the same point
  DEVIATIONS.md's P5 row already names as the trigger to revisit, so it gets a key-
  management endpoint then, not speculatively now.
- The dashboard's `sessionStorage`-cached key has no `HttpOnly` protection against XSS.
  Accepted for now because the dashboard has no cookies and no mutation surface beyond
  mission creation, and because it is explicitly a stopgap, not this ADR's real
  boundary — the real boundary is that `POST /api/missions` and `GET /api/swarm/state`
  are no longer reachable by an untrusted caller with no key at all.
- Every existing `SwarmApi.Api.Tests` call against `/api/*` (via `WebApplicationFactory`)
  will need a key attached once this is implemented — a recorded follow-up cost, not
  addressed here since this ADR is a decision record, not the implementation.
- This closes the *mechanism* half of DEVIATIONS.md's P5 trigger but does not close the
  row itself. Per this repo's own rule ("when a row is fixed, it is deleted, not marked
  done"), the P5 row stays until the middleware and key checks in the previous section
  actually exist in `Program.cs` — this ADR only decides what that implementation will
  look like.

Worked example: the pattern to mirror already exists —
`backend/src/SwarmApi.Application/ISwarmBridge.cs` (interface in Application),
`backend/src/SwarmApi.Infrastructure/RosBridgeOptions.cs` +
`ServiceCollectionExtensions.cs` (options-bound config + one DI-registration entry
point), and `backend/src/SwarmApi.Api/Program.cs` (where that entry point gets called
once, before `builder.Build()`) — `IApiKeyStore`/`ApiKeyOptions`/
`AddApiKeyAuthentication` follow the same three-file shape.
