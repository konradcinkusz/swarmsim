namespace SwarmApi.Domain;

public sealed class Mission
{
    public required Guid Id { get; init; }

    public required string Name { get; init; }

    public required MissionType Type { get; init; }

    public required IReadOnlyList<Vector3> Waypoints { get; init; }

    public required int DroneCount { get; init; }

    public double SpacingMeters { get; init; } = 2.0;

    /// <summary>Follower layout for <see cref="MissionType.LeaderFollowerFormation"/>; ignored for waypoint missions.</summary>
    public FormationShape Formation { get; init; } = FormationShape.Line;

    public required DateTimeOffset CreatedAtUtc { get; init; }

    public MissionStatus Status { get; set; } = MissionStatus.Active;

    /// <summary>When the mission stopped being <see cref="MissionStatus.Active"/>; null while it still is.</summary>
    public DateTimeOffset? EndedAtUtc { get; set; }
}
