namespace SwarmApi.Domain;

/// <summary>
/// Swarm-wide overrides that pre-empt whatever mission is flying. They exist before any
/// autonomous caller does on purpose: the first thing an operator needs from an API that
/// can launch drones is a way to bring them back.
/// </summary>
public enum SwarmCommand
{
    /// <summary>Fly back to the launch position and land there.</summary>
    ReturnToLaunch,

    /// <summary>Descend and land where each drone is now.</summary>
    Land,

    /// <summary>Stop and hold position in the air.</summary>
    Hold,
}
