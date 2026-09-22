namespace SwarmApi.Domain;

/// <summary>One drone's part in a plan: the polyline it is expected to fly, from where it starts.</summary>
public sealed record PlannedDronePath(string DroneId, IReadOnlyList<Vector3> Path, double LengthMeters);

/// <summary>Two drones whose planned paths bring them closer than the minimum separation.</summary>
public sealed record PlanConflict(string DroneA, string DroneB, double AtSeconds, double DistanceMeters);

/// <summary>
/// What a plan will do, computed before anything flies: every drone's path, how long the
/// longest takes at the planning speed, and every pair of drones that would come too close.
/// The assumptions it rests on travel with it, because a preview is only as good as they are.
/// </summary>
public sealed record PlanPreview(
    IReadOnlyList<PlannedDronePath> Drones,
    double EstimatedDurationSeconds,
    double? MinSeparationMeters,
    IReadOnlyList<PlanConflict> Conflicts,
    IReadOnlyList<string> Assumptions);
