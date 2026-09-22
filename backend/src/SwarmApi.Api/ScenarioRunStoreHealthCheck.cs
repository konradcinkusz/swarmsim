using Microsoft.Extensions.Diagnostics.HealthChecks;
using SwarmApi.Application;

namespace SwarmApi.Api;

/// <summary>Where scenario runs are kept, and how many (P8: an in-memory store says so).</summary>
public sealed class ScenarioRunStoreHealthCheck(IScenarioRunStore store) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken cancellationToken = default) =>
        Task.FromResult(HealthCheckResult.Healthy(
            $"Scenario runs: {store.Mode}",
            new Dictionary<string, object> { ["scenarioRuns"] = store.Mode, ["runs"] = store.Count }));
}
