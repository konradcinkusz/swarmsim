namespace SwarmApi.Domain;

public sealed class Mission
{
    public required Guid Id { get; init; }

    public required string Name { get; init; }

    public required MissionType Type { get; init; }

    public required IReadOnlyList<Vector3> Waypoints { get; init; }

    public required int DroneCount { get; init; }

    public double SpacingMeters { get; init; } = 2.0;

    public required DateTimeOffset CreatedAtUtc { get; init; }
}
