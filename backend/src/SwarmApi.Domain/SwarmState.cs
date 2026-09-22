namespace SwarmApi.Domain;

public sealed class SwarmState
{
    public required IReadOnlyList<DroneState> Drones { get; init; }

    public Guid? ActiveMissionId { get; init; }

    /// <summary>True once every drone assigned to <see cref="ActiveMissionId"/> has finished its part of it.</summary>
    public bool ActiveMissionComplete { get; init; }

    public required DateTimeOffset TimestampUtc { get; init; }

    public required SwarmBridgeMode BridgeMode { get; init; }
}
