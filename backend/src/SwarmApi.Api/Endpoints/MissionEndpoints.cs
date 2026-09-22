using SwarmApi.Application;
using SwarmApi.Application.Contracts;

namespace SwarmApi.Api.Endpoints;

/// <summary>Transport only (P9): bind, delegate to <see cref="MissionService"/>, map its outcome to an HTTP response.</summary>
public static class MissionEndpoints
{
    /// <summary>
    /// Writes (create, abort) carry no auth metadata: under Enforced mode's deny-by-default
    /// fallback policy they require a token. The read stays open, per
    /// docs/adr/0005-mcp-server-and-bearer-auth.md.
    /// </summary>
    public static RouteGroupBuilder MapMissionEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/missions").WithTags("Missions");

        group.MapPost("/", async (CreateMissionRequest request, MissionService missions, CancellationToken ct) =>
        {
            try
            {
                var mission = await missions.CreateMissionAsync(request, ct);
                return Results.Created($"/api/missions/{mission.Id}", mission);
            }
            catch (MissionValidationException ex)
            {
                return Problems.Validation(ex);
            }
            catch (SwarmUnavailableException ex)
            {
                return Problems.SwarmUnavailable(ex);
            }
        });

        group.MapGet("/{id:guid}", async (Guid id, MissionService missions, CancellationToken ct) =>
        {
            var mission = await missions.GetMissionAsync(id, ct);
            return mission is not null ? Results.Ok(mission) : Results.NotFound();
        }).AllowAnonymous();

        group.MapPost("/{id:guid}/abort", async (
            Guid id, AbortMissionRequest? request, MissionService missions, CancellationToken ct) =>
        {
            try
            {
                var mission = await missions.AbortMissionAsync(id, request, ct);
                return mission is not null ? Results.Ok(mission) : Results.NotFound();
            }
            catch (MissionValidationException ex)
            {
                return Problems.Validation(ex);
            }
            catch (MissionStateException ex)
            {
                return Results.Problem(ex.Message, statusCode: StatusCodes.Status409Conflict, title: "Mission is not active");
            }
            catch (SwarmUnavailableException ex)
            {
                return Problems.SwarmUnavailable(ex);
            }
        });

        return group;
    }
}
