namespace SwarmApi.Application;

/// <summary>
/// The envelope every mission must fit inside, checked before anything is dispatched.
/// Bound from the <c>Missions</c> configuration section (env: <c>Missions__MaxAltitudeMeters</c>
/// and so on), so a deployment can tighten it without a code change. The defaults are
/// conservative on purpose: 120 m is the EU open-category altitude ceiling, and 1 km from
/// the origin is far beyond anything the simulation world renders.
/// </summary>
public sealed record MissionLimits
{
    public const string SectionName = "Missions";

    public static readonly MissionLimits Default = new();

    /// <summary>M1's own scope ("3-5 instancji"); raise deliberately, not silently.</summary>
    public int MaxDroneCount { get; init; } = 5;

    /// <summary>Highest waypoint altitude accepted (world-frame z, metres above the ground plane).</summary>
    public double MaxAltitudeMeters { get; init; } = 120;

    /// <summary>A circular geofence around the world origin; no waypoint may lie outside it.</summary>
    public double GeofenceRadiusMeters { get; init; } = 1000;

    public int MaxWaypoints { get; init; } = 100;

    public int MaxNameLength { get; init; } = 200;
}
