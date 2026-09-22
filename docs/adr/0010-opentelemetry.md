# ADR-0010: OpenTelemetry in the shared kernel, off until an endpoint is named

## Status

Accepted (2026-09-22). Closes the P15 row of the deviation register.

## Context

P15 asks for OTLP-first observability: traces, metrics and logs exported to whatever
`OTEL_EXPORTER_OTLP_ENDPOINT` names, with health probes left out of traces. `SwarmApi.Api`
had none. The deviation register gave a reason — "no collector endpoint exists to export to
yet" — which is a reason not to *configure* an endpoint, not a reason not to *emit*.
Telemetry added later is telemetry missing from every incident before that.

Two constraints shape how it is added:

- **The dependency budget.** Runtime code ships no third-party NuGet package except JWT
  bearer validation (ADR-0005). OTLP export cannot be done with the shared framework alone:
  the BCL has `ActivitySource` and `Meter`, but no exporter.
- **P8's degrade shape.** Every optional integration here has a visible "off" mode — the
  simulated swarm, Open auth — reported by `/health` and the startup log. Telemetry without
  a collector must be the same: nothing exported, nothing failing, and saying so.

## Decision

- **`SwarmApi.ServiceDefaults` wires OpenTelemetry** (`Telemetry.AddTelemetry`, called from
  `AddServiceDefaults`): traces (ASP.NET Core, minus `/health` and `/alive`), metrics
  (ASP.NET Core, .NET runtime) and logs.
  - With `OTEL_EXPORTER_OTLP_ENDPOINT` set, it exports over OTLP, configured by the
    standard `OTEL_EXPORTER_OTLP_*` variables.
  - Without it, it exports nothing.
  - `/health` reports `telemetry: "Otlp" | "Off"`, and the startup log says which.
- **Four packages, in the kernel only:** `OpenTelemetry.Extensions.Hosting`,
  `OpenTelemetry.Exporter.OpenTelemetryProtocol`, `OpenTelemetry.Instrumentation.AspNetCore`
  and `OpenTelemetry.Instrumentation.Runtime`, all 1.19.x. Their net8.0 dependencies are
  Microsoft.Extensions 8.0.x, the shared framework's own. They are the second recorded
  exception to the budget. They are not hand-rolled for the same reason JWT validation was
  not: an exporter is protocol code with retries and batching, and it is where subtle bugs
  live.
- **The service emits its own signals through the BCL** (`SwarmTelemetry`, in
  `SwarmApi.Application`, so that layer still needs no package).
  - Spans: `mission.dispatch`, `plan.propose`, `plan.dispatch`.
  - Counters: missions dispatched (by type and route: `direct` or `plan`), missions ended
    (by outcome), plans proposed (by preview status), plan decisions, and dispatches
    refused (by reason: `code` or `state`).
  - Every tag comes from a bounded set, never an id (METRICS-EXPOSITION §1); a test holds
    that, and ids appear only on spans.
  - `AddServiceDefaults(SwarmTelemetry.Name)` is how a service hands its source names to
    the kernel. The kernel still references no other SwarmApi project.
- **No Azure Monitor exporter.** P15 adds one when `APPLICATIONINSIGHTS_CONNECTION_STRING`
  is present; ADR-0007 chose Fly.io, so there is nothing to connect it to.

## Consequences

- The P15 row is deleted: the service is instrumented, and turning export on is
  configuration — a Fly secret, when a collector exists
  (`flyio/INFRASTRUCTURE-ANALYSIS.md`).
- The budget now has two exceptions, both in the README's dependency table and in
  `backend/Directory.Packages.props`: JWT bearer validation (ADR-0005) and OpenTelemetry
  (this ADR). The kernel grew by 90 lines, well under its 800-line ceiling.
- The swarm's own side (ROS 2 nodes, MAVROS, PX4) is not instrumented; PX4 writes its own
  ULog. Tracing a mission from the API into the swarm would need a propagated context in
  the rosbridge contract. That is a contract change (P11), left until the first time it
  would have answered a question.

Worked example: `backend/src/SwarmApi.ServiceDefaults/Telemetry.cs`,
`backend/src/SwarmApi.Application/SwarmTelemetry.cs`,
`backend/tests/SwarmApi.Application.Tests/SwarmTelemetryTests.cs`,
`backend/tests/SwarmApi.Api.Tests/TelemetryTests.cs`.
