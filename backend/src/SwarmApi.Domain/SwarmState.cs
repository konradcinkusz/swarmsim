namespace SwarmApi.Domain;

public sealed class SwarmState
{
    public required IReadOnlyList<DroneState> Drones { get; init; }

    public Guid? ActiveMissionId { get; init; }

    public required DateTimeOffset TimestampUtc { get; init; }

    public required SwarmBridgeMode BridgeMode { get; init; }
}
