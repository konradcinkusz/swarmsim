namespace SwarmApi.Domain;

/// <summary>Where a mission plan is on its way from proposal to flight.</summary>
public enum MissionPlanStatus
{
    /// <summary>Waiting for a person to approve or reject it.</summary>
    PendingApproval,

    /// <summary>Its paths bring two drones too close: it cannot be approved, only re-planned.</summary>
    Conflicted,

    /// <summary>Approved; dispatchable once, with the approval code, until the approval expires.</summary>
    Approved,

    Rejected,

    /// <summary>Dispatched as a mission (<see cref="MissionPlan.MissionId"/>).</summary>
    Dispatched,

    /// <summary>Nobody acted on it in time, or its approval lapsed unused.</summary>
    Expired,
}
