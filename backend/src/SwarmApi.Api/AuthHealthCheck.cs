using Microsoft.Extensions.Diagnostics.HealthChecks;
using SwarmApi.Application;

namespace SwarmApi.Api;

/// <summary>
/// The P8 "visible degradation" health check for the `authservice` dependency: reports
/// whether bearer-token auth is enforced. Always Healthy — Open is a working degraded
/// state, not a failure — so this exists to be read, not to gate readiness. See
/// docs/adr/0005-mcp-server-and-bearer-auth.md.
/// </summary>
public sealed class AuthHealthCheck(AuthStatus status) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var data = new Dictionary<string, object> { ["auth"] = status.Mode.ToString() };
        return Task.FromResult(HealthCheckResult.Healthy($"Auth mode: {status.Mode}", data));
    }
}
