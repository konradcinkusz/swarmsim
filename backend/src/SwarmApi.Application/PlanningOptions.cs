namespace SwarmApi.Application;

/// <summary>
/// How mission plans are checked and how long a decision may take (the <c>Planning</c>
/// configuration section; env <c>Planning__MinSeparationMeters</c> and so on).
/// </summary>
public sealed record PlanningOptions
{
    public const string SectionName = "Planning";

    public static readonly PlanningOptions Default = new();

    /// <summary>Two drones planned closer than this are a conflict; the plan cannot be approved.</summary>
    public double MinSeparationMeters { get; init; } = 2.0;

    /// <summary>The common speed the deconfliction check flies every drone at — the swarm's cruise speed.</summary>
    public double NominalSpeedMetersPerSecond { get; init; } = 2.0;

    /// <summary>
    /// Pad layout for a drone the swarm has not reported yet: drone_n on (0, spacing × (n−1), 0),
    /// as in simulation/px4-configs/. A reported drone starts from its reported position.
    /// </summary>
    public double PadSpacingMeters { get; init; } = 3.0;

    /// <summary>A plan nobody approves or rejects within this expires.</summary>
    public double DecisionWindowMinutes { get; init; } = 60;

    /// <summary>An approval not used to dispatch within this lapses; the plan then expires.</summary>
    public double ApprovalValidityMinutes { get; init; } = 10;
}
