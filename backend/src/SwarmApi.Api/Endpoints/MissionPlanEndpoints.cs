using SwarmApi.Api.Idempotency;
using SwarmApi.Application;
using SwarmApi.Application.Contracts;

namespace SwarmApi.Api.Endpoints;

/// <summary>
/// The write gate for agents (docs/adr/0009), transport only (P9): propose a plan, read it,
/// approve or reject it, dispatch it with the approval code. Every write honours
/// <c>Idempotency-Key</c>; the reads stay open, like the other reads.
/// </summary>
public static class MissionPlanEndpoints
{
    public const int MaxListLimit = 100;

    public static RouteGroupBuilder MapMissionPlanEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/mission-plans").WithTags("Mission plans");

        group.MapPost("/", async (
            CreateMissionRequest request, HttpContext http, MissionPlanService plans, CancellationToken ct) =>
        {
            try
            {
                var plan = await plans.CreatePlanAsync(request, Caller.Subject(http.User), ct);
                return Results.Created($"/api/mission-plans/{plan.Id}", plan);
            }
            catch (MissionValidationException ex)
            {
                return Problems.Validation(ex);
            }
        }).WithIdempotency();

        group.MapGet("/", (int? limit, MissionPlanService plans) =>
            Results.Ok(plans.RecentPlans(Math.Clamp(limit ?? 20, 1, MaxListLimit)))).AllowAnonymous();

        group.MapGet("/{id:guid}", (Guid id, MissionPlanService plans) =>
            plans.GetPlan(id) is { } plan ? Results.Ok(plan) : Results.NotFound()).AllowAnonymous();

        group.MapPost("/{id:guid}/approve", (Guid id, HttpContext http, MissionPlanService plans) =>
            Decide(() => plans.Approve(id, Caller.Subject(http.User)))).WithIdempotency();

        group.MapPost("/{id:guid}/reject", (Guid id, HttpContext http, MissionPlanService plans) =>
            Decide(() => plans.Reject(id, Caller.Subject(http.User)))).WithIdempotency();

        group.MapPost("/{id:guid}/dispatch", async (
            Guid id, DispatchPlanRequest? request, MissionPlanService plans, CancellationToken ct) =>
        {
            try
            {
                var mission = await plans.DispatchAsync(id, request?.ApprovalCode, ct);
                return mission is not null ? Results.Created($"/api/missions/{mission.Id}", mission) : Results.NotFound();
            }
            catch (PlanStateException ex)
            {
                return Problems.PlanState(ex);
            }
            catch (ApprovalRefusedException ex)
            {
                return Problems.ApprovalRefused(ex);
            }
            catch (SwarmUnavailableException ex)
            {
                return Problems.SwarmUnavailable(ex);
            }
        }).WithIdempotency();

        return group;
    }

    private static IResult Decide<T>(Func<T?> decision)
        where T : class
    {
        try
        {
            return decision() is { } outcome ? Results.Ok(outcome) : Results.NotFound();
        }
        catch (PlanStateException ex)
        {
            return Problems.PlanState(ex);
        }
        catch (ApprovalRefusedException ex)
        {
            return Problems.ApprovalRefused(ex);
        }
    }
}
