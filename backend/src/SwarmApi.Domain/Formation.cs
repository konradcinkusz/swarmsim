namespace SwarmApi.Domain;

/// <summary>
/// Leader-follower formation offsets and separation checking (M2), mirroring
/// <c>swarm_coordination/formation.py</c>.
/// </summary>
public static class Formation
{
    /// <summary>Offsets for <paramref name="count"/> followers in a line behind the leader.</summary>
    public static IReadOnlyList<Vector3> Line(int count, double spacingMeters)
    {
        if (count < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(count), "count must be non-negative.");
        }

        var offsets = new List<Vector3>(count);
        for (var i = 0; i < count; i++)
        {
            offsets.Add(new Vector3(-spacingMeters * (i + 1), 0, 0));
        }

        return offsets;
    }

    /// <summary>
    /// Offsets for <paramref name="count"/> followers in a V behind the leader, alternating
    /// sides: follower i sits <c>rank = i/2 + 1</c> spacings back and the same distance out.
    /// Mirrors <c>swarm_coordination/formation.py</c>'s <c>v_formation</c>.
    /// </summary>
    public static IReadOnlyList<Vector3> V(int count, double spacingMeters)
    {
        if (count < 0)
        {
            throw new ArgumentOutOfRangeException(nameof(count), "count must be non-negative.");
        }

        var offsets = new List<Vector3>(count);
        for (var i = 0; i < count; i++)
        {
            var rank = (i / 2) + 1;
            var side = i % 2 == 0 ? 1 : -1;
            offsets.Add(new Vector3(-spacingMeters * rank, side * spacingMeters * rank, 0));
        }

        return offsets;
    }

    /// <summary>Follower offsets for <paramref name="shape"/>.</summary>
    public static IReadOnlyList<Vector3> Offsets(FormationShape shape, int count, double spacingMeters) =>
        shape switch
        {
            FormationShape.Line => Line(count, spacingMeters),
            FormationShape.V => V(count, spacingMeters),
            _ => throw new ArgumentOutOfRangeException(nameof(shape), shape, "Unknown formation shape."),
        };

    /// <summary>The smallest pairwise distance among <paramref name="positions"/>, or null if fewer than two.</summary>
    public static double? MinSeparation(IReadOnlyList<Vector3> positions)
    {
        if (positions.Count < 2)
        {
            return null;
        }

        double? best = null;
        for (var i = 0; i < positions.Count; i++)
        {
            for (var j = i + 1; j < positions.Count; j++)
            {
                var distance = positions[i].DistanceTo(positions[j]);
                if (best is null || distance < best)
                {
                    best = distance;
                }
            }
        }

        return best;
    }

    /// <summary>True if any two drones are closer than <paramref name="minDistanceMeters"/> — M2's no-collision check.</summary>
    public static bool HasCollision(IReadOnlyList<Vector3> positions, double minDistanceMeters)
    {
        var separation = MinSeparation(positions);
        return separation is not null && separation < minDistanceMeters;
    }
}
