using SwarmApi.Application;
using SwarmApi.Application.Contracts;

namespace SwarmApi.Api.Endpoints;

/// <summary>Transport only (P9): bind, delegate to <see cref="MissionService"/>, map its outcome to an HTTP response.</summary>
public static class MissionEndpoints
{
    /// <param name="requireAuthentication">
    /// Gates <c>POST /</c> (mission creation — the one write an MCP-driven Agent would
    /// invoke) behind a valid bearer token when true. <c>GET /{id}</c> stays open either
    /// way — see docs/adr/0005-mcp-server-and-bearer-auth.md for why the scope stops
    /// there for now.
    /// </param>
    public static RouteGroupBuilder MapMissionEndpoints(this WebApplication app, bool requireAuthentication)
    {
        var group = app.MapGroup("/api/missions").WithTags("Missions");

        var createMission = group.MapPost("/", async (CreateMissionRequest request, MissionService missionService, CancellationToken ct) =>
        {
            try
            {
                var mission = await missionService.CreateMissionAsync(request, ct);
                return Results.Created($"/api/missions/{mission.Id}", mission);
            }
            catch (MissionValidationException ex)
            {
                return Results.ValidationProblem(new Dictionary<string, string[]>
                {
                    ["request"] = [.. ex.Errors],
                });
            }
        });

        if (requireAuthentication)
        {
            createMission.RequireAuthorization();
        }

        group.MapGet("/{id:guid}", async (Guid id, MissionService missionService, CancellationToken ct) =>
        {
            var mission = await missionService.GetMissionAsync(id, ct);
            return mission is not null ? Results.Ok(mission) : Results.NotFound();
        });

        return group;
    }
}
