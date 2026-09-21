using SwarmApi.Application;
using SwarmApi.Application.Contracts;

namespace SwarmApi.Api.Endpoints;

/// <summary>Transport only (P9): bind, delegate to <see cref="MissionService"/>, map its outcome to an HTTP response.</summary>
public static class MissionEndpoints
{
    public static RouteGroupBuilder MapMissionEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/missions").WithTags("Missions");

        group.MapPost("/", async (CreateMissionRequest request, MissionService missionService, CancellationToken ct) =>
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

        group.MapGet("/{id:guid}", async (Guid id, MissionService missionService, CancellationToken ct) =>
        {
            var mission = await missionService.GetMissionAsync(id, ct);
            return mission is not null ? Results.Ok(mission) : Results.NotFound();
        });

        return group;
    }
}
