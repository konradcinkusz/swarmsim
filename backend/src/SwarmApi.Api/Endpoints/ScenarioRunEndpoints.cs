using Microsoft.AspNetCore.Mvc;
using SwarmApi.Api.Idempotency;
using SwarmApi.Application;
using SwarmApi.Application.Contracts;

namespace SwarmApi.Api.Endpoints;

/// <summary>
/// Stored scenario runs (docs/adr/0011), transport only (P9): ingest a report, list, read,
/// compare two. Unlike the swarm reads, these need a token in Enforced mode: a run carries
/// someone's scenarios and results, not the state of a shared simulator.
/// </summary>
public static class ScenarioRunEndpoints
{
    /// <summary>A report of a thousand scenarios with several seeds each is well under this.</summary>
    public const long MaxReportBytes = 4 * 1024 * 1024;

    public static RouteGroupBuilder MapScenarioRunEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/scenario-runs").WithTags("Scenario runs");

        group.MapPost("/", async (
            IngestScenarioRunRequest request, HttpContext http, ScenarioRunService runs, CancellationToken ct) =>
        {
            try
            {
                var run = await runs.IngestAsync(request, Caller.Subject(http.User), ct);
                return Results.Created($"/api/scenario-runs/{run.Id}", run);
            }
            catch (ScenarioRunValidationException ex)
            {
                return Problems.ScenarioRunValidation(ex);
            }
        }).WithIdempotency().WithMetadata(new RequestSizeLimitAttribute(MaxReportBytes));

        group.MapGet("/", async (int? limit, ScenarioRunService runs, CancellationToken ct) =>
            Results.Ok(await runs.RecentAsync(limit ?? 20, ct)));

        group.MapGet("/{id:guid}", async (Guid id, ScenarioRunService runs, CancellationToken ct) =>
            await runs.GetAsync(id, ct) is { } run ? Results.Ok(run) : Results.NotFound());

        group.MapGet("/compare", async (
            [FromQuery(Name = "base")] Guid baseId, [FromQuery(Name = "head")] Guid headId,
            ScenarioRunService runs, CancellationToken ct) =>
            await runs.CompareAsync(baseId, headId, ct) is { } comparison ? Results.Ok(comparison) : Results.NotFound());

        return group;
    }
}
