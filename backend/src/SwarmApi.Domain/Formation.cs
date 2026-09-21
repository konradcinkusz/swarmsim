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
