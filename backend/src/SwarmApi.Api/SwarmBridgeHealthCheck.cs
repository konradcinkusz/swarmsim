using Microsoft.Extensions.Diagnostics.HealthChecks;
using SwarmApi.Application;
using SwarmApi.Domain;

namespace SwarmApi.Api;

/// <summary>
/// The P8 "visible degradation" health check: reports which <see cref="ISwarmBridge"/> is
/// active, whether it is connected right now, and how old the last swarm state is.
/// Simulated is a working degraded state (Healthy); a configured swarm that has dropped
/// its connection is Degraded — still HTTP 200, because restarting this process would not
/// bring rosbridge back, but visibly not Healthy.
/// </summary>
public sealed class SwarmBridgeHealthCheck(ISwarmBridge bridge, TimeProvider time) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var mode = bridge.Mode;
        var data = new Dictionary<string, object> { ["swarmBridge"] = mode.ToString() };
        if (bridge.LastStateReceivedUtc is { } last)
        {
            data["lastStateAgeSeconds"] = Math.Round((time.GetUtcNow() - last).TotalSeconds, 2);
        }

        return Task.FromResult(mode == SwarmBridgeMode.Disconnected
            ? HealthCheckResult.Degraded("Swarm bridge disconnected; reconnecting in the background.", data: data)
            : HealthCheckResult.Healthy($"Swarm bridge mode: {mode}", data));
    }
}
