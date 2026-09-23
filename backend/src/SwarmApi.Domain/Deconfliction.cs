namespace SwarmApi.Domain;

/// <summary>
/// Plan-time deconfliction: every drone flies its polyline at the same nominal speed, all
/// departing together, and every pair's distance is sampled over time. A pair that comes
/// closer than the minimum separation is a conflict, reported once at its closest approach.
///
/// It is a check on the plan, not a guarantee about the flight — real drones do not keep a
/// common speed — but it catches the geometry that makes a collision likely, such as a
/// formation whose slots make a drone cross its neighbours on the way in (the scenario
/// study's first finding, docs/research/scenario-study.md).
/// </summary>
public static class Deconfliction
{
    /// <summary>Samples no finer than this, and no more samples than <see cref="MaxSamples"/>.</summary>
    public const double SampleSeconds = 0.1;

    public const int MaxSamples = 20_000;

    public static (double? MinSeparation, IReadOnlyList<PlanConflict> Conflicts) Check(
        IReadOnlyList<PlannedDronePath> paths, double speedMetersPerSecond, double minSeparationMeters)
    {
        if (speedMetersPerSecond <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(speedMetersPerSecond), "speed must be positive.");
        }

        if (paths.Count < 2)
        {
            return (null, []);
        }

        var duration = paths.Max(p => p.LengthMeters) / speedMetersPerSecond;
        var step = Math.Max(SampleSeconds, duration / MaxSamples);
        var closest = new Dictionary<(int, int), (double Distance, double At)>();

        for (var t = 0.0; t <= duration + step; t += step)
        {
            var positions = paths.Select(p => PositionAt(p.Path, speedMetersPerSecond * t)).ToArray();
            for (var i = 0; i < positions.Length; i++)
            {
                for (var j = i + 1; j < positions.Length; j++)
                {
                    var distance = positions[i].DistanceTo(positions[j]);
                    if (!closest.TryGetValue((i, j), out var best) || distance < best.Distance)
                    {
                        closest[(i, j)] = (distance, t);
                    }
                }
            }
        }

        var conflicts = closest
            .Where(pair => pair.Value.Distance < minSeparationMeters)
            .OrderBy(pair => pair.Value.At)
            .Select(pair => new PlanConflict(
                paths[pair.Key.Item1].DroneId,
                paths[pair.Key.Item2].DroneId,
                Math.Round(pair.Value.At, 1),
                Math.Round(pair.Value.Distance, 2)))
            .ToList();
        return (Math.Round(closest.Values.Min(v => v.Distance), 2), conflicts);
    }

    /// <summary>The point <paramref name="distanceMeters"/> along <paramref name="path"/>; its end once past it.</summary>
    public static Vector3 PositionAt(IReadOnlyList<Vector3> path, double distanceMeters)
    {
        var remaining = distanceMeters;
        for (var i = 1; i < path.Count; i++)
        {
            var segment = path[i].DistanceTo(path[i - 1]);
            if (remaining <= segment)
            {
                return segment == 0 ? path[i] : path[i - 1] + (path[i] - path[i - 1]).Scale(remaining / segment);
            }

            remaining -= segment;
        }

        return path[^1];
    }

    public static double Length(IReadOnlyList<Vector3> path)
    {
        var length = 0.0;
        for (var i = 1; i < path.Count; i++)
        {
            length += path[i].DistanceTo(path[i - 1]);
        }

        return length;
    }
}
