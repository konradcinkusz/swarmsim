using Microsoft.Extensions.Diagnostics.HealthChecks;
using SwarmApi.Application;

namespace SwarmApi.Api;

/// <summary>
/// The P8 "visible degradation" health check: reports which <see cref="ISwarmBridge"/>
/// is active. Always Healthy — Simulated is a working degraded state, not a failure —
/// so this exists to be read, not to gate readiness.
/// </summary>
public sealed class SwarmBridgeHealthCheck(ISwarmBridge bridge) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var data = new Dictionary<string, object> { ["swarmBridge"] = bridge.Mode.ToString() };
        return Task.FromResult(HealthCheckResult.Healthy($"Swarm bridge mode: {bridge.Mode}", data));
    }
}
