namespace SwarmApi.Application.Contracts;

public sealed record WaypointDto(double X, double Y, double Z);

/// <summary>
/// The <c>POST /api/missions</c> request body. <see cref="Type"/> is a string
/// (<c>"waypoint"</c> | <c>"formation"</c>) rather than the domain enum, because the
/// wire contract and the domain model are allowed to diverge (P11) and validating an
/// unrecognized string gives a caller a clean 400 instead of a model-binding failure.
/// </summary>
public sealed record CreateMissionRequest(
    string Name,
    string Type,
    IReadOnlyList<WaypointDto> Waypoints,
    int DroneCount,
    double SpacingMeters = 2.0);
