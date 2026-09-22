namespace SwarmApi.Domain;

public sealed class DroneState
{
    public required string Id { get; init; }

    /// <summary>Position in the shared world frame (ENU, metres), not the drone's own local frame.</summary>
    public required Vector3 Position { get; set; }

    /// <summary>Remaining battery, or null when the bridge has no reading. Never defaulted to a plausible value.</summary>
    public double? BatteryPercent { get; set; }

    public DroneStatus Status { get; set; } = DroneStatus.Unknown;

    /// <summary>Whether the autopilot reports the motors armed; null when unknown.</summary>
    public bool? Armed { get; set; }

    /// <summary>The autopilot's own flight-mode name (e.g. PX4's OFFBOARD, AUTO.RTL); null when unknown.</summary>
    public string? FlightMode { get; set; }

    public int CurrentWaypointIndex { get; set; }

    public required DateTimeOffset LastUpdatedUtc { get; set; }
}
