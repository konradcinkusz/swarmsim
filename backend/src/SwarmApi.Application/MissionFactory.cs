using SwarmApi.Application.Contracts;
using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// Turns a validated wire request into the domain <see cref="Mission"/>, once, here —
/// rather than in each <see cref="ISwarmBridge"/>, which used to duplicate this mapping and
/// so depended on the HTTP contract (P11: the edge translates, nothing downstream does).
/// </summary>
public static class MissionFactory
{
    public static Mission Create(CreateMissionRequest request, DateTimeOffset now) => new()
    {
        Id = Guid.NewGuid(),
        Name = request.Name.Trim(),
        Type = request.Type == "formation" ? MissionType.LeaderFollowerFormation : MissionType.WaypointFollow,
        Formation = request.Formation == "v" ? FormationShape.V : FormationShape.Line,
        Waypoints = request.Waypoints.Select(w => new Vector3(w.X, w.Y, w.Z)).ToList(),
        DroneCount = request.DroneCount,
        SpacingMeters = request.SpacingMeters,
        CreatedAtUtc = now,
        Status = MissionStatus.Active,
    };

    /// <summary>A planned mission as it takes off: same id and route, dispatched now.</summary>
    public static Mission Launch(Mission planned, DateTimeOffset now) => new()
    {
        Id = planned.Id,
        Name = planned.Name,
        Type = planned.Type,
        Formation = planned.Formation,
        Waypoints = planned.Waypoints,
        DroneCount = planned.DroneCount,
        SpacingMeters = planned.SpacingMeters,
        CreatedAtUtc = now,
        Status = MissionStatus.Active,
    };

    /// <summary>Maps the abort body's action to a swarm command; unknown values are a validation error.</summary>
    public static SwarmCommand AbortCommand(AbortMissionRequest? request) => request?.Action switch
    {
        null or "" or "rtl" => SwarmCommand.ReturnToLaunch,
        "land" => SwarmCommand.Land,
        "hold" => SwarmCommand.Hold,
        _ => throw new MissionValidationException(["Action must be 'rtl', 'land' or 'hold'."]),
    };
}
