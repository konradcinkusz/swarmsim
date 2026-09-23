namespace SwarmApi.Domain;

/// <summary>
/// A mission proposed but not yet flown. An agent can create one; only a person can approve
/// it; and it flies only when dispatched with the single-use code the approval produced
/// (docs/adr/0009). The mission it would dispatch is built up front, so what was previewed
/// and approved is exactly what flies.
/// </summary>
public sealed class MissionPlan
{
    public required Guid Id { get; init; }

    /// <summary>The mission this plan dispatches; its id is the mission's id once it flies.</summary>
    public required Mission Mission { get; init; }

    public required PlanPreview Preview { get; init; }

    public required DateTimeOffset CreatedAtUtc { get; init; }

    /// <summary>The authenticated subject that proposed it; null in Open mode.</summary>
    public string? CreatedBy { get; init; }

    /// <summary>A plan nobody approves by then expires.</summary>
    public required DateTimeOffset DecideByUtc { get; init; }

    public MissionPlanStatus Status { get; set; }

    public DateTimeOffset? DecidedAtUtc { get; set; }

    public string? DecidedBy { get; set; }

    /// <summary>The approval code's SHA-256 — never the code itself. Null once used or before approval.</summary>
    public byte[]? ApprovalCodeHash { get; set; }

    /// <summary>An approved plan not dispatched by then expires.</summary>
    public DateTimeOffset? ApprovalExpiresAtUtc { get; set; }

    public Guid? MissionId { get; set; }
}
