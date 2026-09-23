using SwarmApi.Domain;

namespace SwarmApi.Application.Contracts;

/// <summary>A plan as the API shows it: everything except the approval code's hash.</summary>
public sealed record MissionPlanView(
    Guid Id,
    MissionPlanStatus Status,
    string Name,
    MissionType Type,
    FormationShape Formation,
    IReadOnlyList<Vector3> Waypoints,
    int DroneCount,
    double SpacingMeters,
    PlanPreview Preview,
    DateTimeOffset CreatedAtUtc,
    string? CreatedBy,
    DateTimeOffset DecideByUtc,
    DateTimeOffset? DecidedAtUtc,
    string? DecidedBy,
    DateTimeOffset? ApprovalExpiresAtUtc,
    Guid? MissionId)
{
    public static MissionPlanView From(MissionPlan plan) => new(
        plan.Id,
        plan.Status,
        plan.Mission.Name,
        plan.Mission.Type,
        plan.Mission.Formation,
        plan.Mission.Waypoints,
        plan.Mission.DroneCount,
        plan.Mission.SpacingMeters,
        plan.Preview,
        plan.CreatedAtUtc,
        plan.CreatedBy,
        plan.DecideByUtc,
        plan.DecidedAtUtc,
        plan.DecidedBy,
        plan.ApprovalExpiresAtUtc,
        plan.MissionId);
}

/// <summary>
/// What approving a plan returns — the only response that ever carries the approval code.
/// Whoever holds the code can dispatch the plan once, until <see cref="ExpiresAtUtc"/>.
/// </summary>
public sealed record PlanApproval(MissionPlanView Plan, string ApprovalCode, DateTimeOffset ExpiresAtUtc);

/// <summary>The <c>POST /api/mission-plans/{id}/dispatch</c> body.</summary>
public sealed record DispatchPlanRequest(string? ApprovalCode);

/// <summary>The plan exists but its status does not allow the operation; mapped to 409.</summary>
public sealed class PlanStateException(string message) : Exception(message);

/// <summary>The caller may not do this to this plan (wrong code, or approving their own plan); mapped to 403.</summary>
public sealed class ApprovalRefusedException(string message) : Exception(message);
