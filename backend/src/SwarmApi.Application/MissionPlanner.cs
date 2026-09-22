using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// Builds a plan's preview: the path each drone is expected to fly, from where it starts,
/// and the deconfliction check over them. Mirrors how the swarm assigns work
/// (swarm_coordination/mission_planning.py): a waypoint mission gives drone i the route on
/// its own lane (y + i × spacing); a formation gives drone_1 the route and every follower
/// the route shifted by its slot offset.
/// </summary>
public static class MissionPlanner
{
    public static PlanPreview Preview(
        Mission mission, IReadOnlyDictionary<string, Vector3> reportedPositions, PlanningOptions options)
    {
        var assumptions = new List<string>
        {
            $"drone_1 … drone_{mission.DroneCount} fly it; the swarm may substitute a drone that is low on battery.",
            $"every drone departs at once and flies its path at {options.NominalSpeedMetersPerSecond:g} m/s.",
        };

        var offsets = mission.Type == MissionType.LeaderFollowerFormation
            ? [Vector3.Zero, .. Formation.Offsets(mission.Formation, mission.DroneCount - 1, mission.SpacingMeters)]
            : Enumerable.Range(0, mission.DroneCount).Select(i => new Vector3(0, i * mission.SpacingMeters, 0)).ToList();

        var unreported = new List<string>();
        var paths = new List<PlannedDronePath>(mission.DroneCount);
        for (var i = 0; i < mission.DroneCount; i++)
        {
            var id = $"drone_{i + 1}";
            if (!reportedPositions.TryGetValue(id, out var start))
            {
                start = new Vector3(0, i * options.PadSpacingMeters, 0);
                unreported.Add(id);
            }

            List<Vector3> path = [start, .. mission.Waypoints.Select(w => w + offsets[i])];
            paths.Add(new PlannedDronePath(id, path, Math.Round(Deconfliction.Length(path), 2)));
        }

        if (unreported.Count > 0)
        {
            assumptions.Add(
                $"{string.Join(", ", unreported)} not reported by the swarm: assumed on the pad at " +
                $"(0, {options.PadSpacingMeters:g} × (n−1), 0).");
        }

        var (minSeparation, conflicts) = Deconfliction.Check(
            paths, options.NominalSpeedMetersPerSecond, options.MinSeparationMeters);
        var duration = paths.Max(p => p.LengthMeters) / options.NominalSpeedMetersPerSecond;
        return new PlanPreview(paths, Math.Round(duration, 1), minSeparation, conflicts, assumptions);
    }
}
