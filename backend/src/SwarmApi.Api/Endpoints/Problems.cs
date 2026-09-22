using SwarmApi.Application.Contracts;

namespace SwarmApi.Api.Endpoints;

/// <summary>The problem-details shapes the endpoints share, so each failure reads the same wherever it surfaces.</summary>
internal static class Problems
{
    public static IResult Validation(MissionValidationException ex) =>
        Results.ValidationProblem(new Dictionary<string, string[]> { ["request"] = [.. ex.Errors] });

    /// <summary>
    /// 503: the swarm could not be reached, so nothing was dispatched — or, when a send
    /// failed part-way, it may have been. Either way the caller must not assume success.
    /// </summary>
    public static IResult PlanState(PlanStateException ex) =>
        Results.Problem(ex.Message, statusCode: StatusCodes.Status409Conflict, title: "Plan is not in a state that allows this");

    public static IResult ApprovalRefused(ApprovalRefusedException ex) =>
        Results.Problem(ex.Message, statusCode: StatusCodes.Status403Forbidden, title: "Approval refused");

    public static IResult SwarmUnavailable(SwarmUnavailableException ex) =>
        Results.Problem(ex.Message, statusCode: StatusCodes.Status503ServiceUnavailable, title: "Swarm unavailable");
}
