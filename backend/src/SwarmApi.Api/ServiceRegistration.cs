using SwarmApi.Application;

namespace SwarmApi.Api;

/// <summary>
/// The composition root's own wiring, kept out of <c>Program.cs</c> so that file stays a
/// list of capabilities (P9).
/// </summary>
public static class ServiceRegistration
{
    /// <summary>The mission use case and the envelope it validates against (<c>Missions</c> section).</summary>
    public static IServiceCollection AddSwarmMissions(this IServiceCollection services, IConfiguration configuration)
    {
        var limits = configuration.GetSection(MissionLimits.SectionName).Get<MissionLimits>() ?? MissionLimits.Default;
        services.AddSingleton(limits);
        services.AddSingleton(sp => new MissionService(
            sp.GetRequiredService<ISwarmBridge>(), limits, sp.GetRequiredService<TimeProvider>()));
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
