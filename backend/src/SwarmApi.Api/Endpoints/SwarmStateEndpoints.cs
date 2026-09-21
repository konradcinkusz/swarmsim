using SwarmApi.Application;

namespace SwarmApi.Api.Endpoints;

public static class SwarmStateEndpoints
{
    public static RouteGroupBuilder MapSwarmStateEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/swarm").WithTags("Swarm");

        group.MapGet("/state", async (MissionService missionService, CancellationToken ct) =>
            Results.Ok(await missionService.GetSwarmStateAsync(ct)));

        return group;
    }
}
