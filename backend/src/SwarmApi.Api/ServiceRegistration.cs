using SwarmApi.Api.Idempotency;
using SwarmApi.Application;

namespace SwarmApi.Api;

/// <summary>
/// The composition root's own wiring, kept out of <c>Program.cs</c> so that file stays a
/// list of capabilities (P9).
/// </summary>
public static class ServiceRegistration
{
    /// <summary>
    /// The mission use cases — direct dispatch, and the plan → approve → dispatch gate for
    /// agents (docs/adr/0009) — with the envelope they validate against (<c>Missions</c>),
    /// how plans are checked (<c>Planning</c>), and replay-safe writes (<c>Idempotency-Key</c>).
    /// </summary>
    public static IServiceCollection AddSwarmMissions(this IServiceCollection services, IConfiguration configuration)
    {
        var limits = configuration.GetSection(MissionLimits.SectionName).Get<MissionLimits>() ?? MissionLimits.Default;
        var planning = configuration.GetSection(PlanningOptions.SectionName).Get<PlanningOptions>() ?? PlanningOptions.Default;
        services.AddSingleton(limits);
        services.AddSingleton(planning);
        services.AddSingleton(sp => new MissionService(
            sp.GetRequiredService<ISwarmBridge>(), limits, sp.GetRequiredService<TimeProvider>()));
        services.AddSingleton(sp => new MissionPlanService(
            sp.GetRequiredService<MissionService>(),
            sp.GetRequiredService<ISwarmBridge>(),
            limits,
            planning,
            sp.GetRequiredService<TimeProvider>()));
        services.AddSingleton(sp => new IdempotencyStore(sp.GetRequiredService<TimeProvider>()));
        return services;
    }

    /// <summary>The health checks <c>/health</c> reports: which bridge and auth mode are live (P8).</summary>
    public static IServiceCollection AddSwarmHealthChecks(this IServiceCollection services)
    {
        services.AddHealthChecks()
            .AddCheck<SwarmBridgeHealthCheck>("swarm_bridge", tags: ["live"])
            .AddCheck<AuthHealthCheck>("auth", tags: ["live"]);
        return services;
    }
}
