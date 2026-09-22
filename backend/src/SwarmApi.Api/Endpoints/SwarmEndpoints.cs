using SwarmApi.Application;
using SwarmApi.Application.Contracts;

namespace SwarmApi.Api.Endpoints;

public static class SwarmEndpoints
{
    public static RouteGroupBuilder MapSwarmEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/swarm").WithTags("Swarm");

        group.MapGet("/state", async (MissionService missions, CancellationToken ct) =>
            Results.Ok(await missions.GetSwarmStateAsync(ct))).AllowAnonymous();

        // Emergency land-all: every drone lands where it is, whatever it was doing. A write,
        // so it requires a token in Enforced mode like every other write.
        group.MapPost("/land", async (MissionService missions, CancellationToken ct) =>
        {
            try
            {
                await missions.LandAllAsync(ct);
                return Results.Accepted(value: new { command = "Land" });
            }
            catch (SwarmUnavailableException ex)
            {
                return Problems.SwarmUnavailable(ex);
            }
        });

        return group;
    }
}
