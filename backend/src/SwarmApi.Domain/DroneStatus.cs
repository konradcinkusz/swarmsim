namespace SwarmApi.Domain;

/// <summary>
/// What a drone is doing. New values are appended, never inserted: the wire form is the
/// name (JsonStringEnumConverter), but appending keeps any numeric consumer stable too.
/// </summary>
public enum DroneStatus
{
    Idle,
    TakingOff,
    InFlight,
    Landing,
    Landed,
    Error,

    /// <summary>The bridge has no reliable reading — reported instead of a guess.</summary>
    Unknown,

    /// <summary>Flying back to its launch position (return-to-launch).</summary>
    Returning,

    /// <summary>Holding position in the air after a hold command.</summary>
    Holding,
}
