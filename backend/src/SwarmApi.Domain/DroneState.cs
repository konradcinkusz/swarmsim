namespace SwarmApi.Domain;

public sealed class DroneState
{
    public required string Id { get; init; }

    public required Vector3 Position { get; set; }

    public double BatteryPercent { get; set; } = 100.0;

    public DroneStatus Status { get; set; } = DroneStatus.Idle;

    public int CurrentWaypointIndex { get; set; }

    public required DateTimeOffset LastUpdatedUtc { get; set; }
}
