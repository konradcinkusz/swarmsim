using SwarmApi.Domain;
using Xunit;

namespace SwarmApi.Domain.Tests;

public class DeconflictionTests
{
    private static PlannedDronePath Path(string id, params Vector3[] points) =>
        new(id, points, Deconfliction.Length(points));

    [Fact]
    public void Parallel_lanes_three_metres_apart_have_no_conflict()
    {
        var paths = new[]
        {
            Path("drone_1", new(0, 0, 0), new(0, 0, 5), new(20, 0, 5)),
            Path("drone_2", new(0, 3, 0), new(0, 3, 5), new(20, 3, 5)),
        };

        var (minSeparation, conflicts) = Deconfliction.Check(paths, 2.0, 2.0);

        Assert.Empty(conflicts);
        Assert.Equal(3.0, minSeparation);
    }

    [Fact]
    public void Paths_that_cross_at_the_same_time_are_a_conflict_at_the_crossing()
    {
        var paths = new[]
        {
            Path("drone_1", new(-10, 0, 5), new(10, 0, 5)),
            Path("drone_2", new(0, -10, 5), new(0, 10, 5)),
        };

        var (minSeparation, conflicts) = Deconfliction.Check(paths, 2.0, 2.0);

        var conflict = Assert.Single(conflicts);
        Assert.Equal(("drone_1", "drone_2"), (conflict.DroneA, conflict.DroneB));
        Assert.Equal(5.0, conflict.AtSeconds, 1); // both reach the origin after 10 m at 2 m/s
        Assert.Equal(0.0, minSeparation!.Value, 2);
    }

    [Fact]
    public void Paths_that_cross_at_different_times_are_not_a_conflict()
    {
        var paths = new[]
        {
            Path("drone_1", new(-2, 0, 5), new(10, 0, 5)),
            Path("drone_2", new(0, -30, 5), new(0, 10, 5)),
        };

        Assert.Empty(Deconfliction.Check(paths, 2.0, 2.0).Conflicts);
    }

    [Fact]
    public void A_v_formation_launched_from_a_row_of_pads_is_caught_before_it_flies()
    {
        // The scenario study's first finding (scenarios/v_formation_from_pads.yaml): drone_3's
        // way to its slot on the far side of the leader runs through drone_2.
        var offsets = Formation.V(2, 3.0);
        var route = new Vector3(0, 0, 6);
        var paths = new[]
        {
            Path("drone_1", new(0, 0, 0), route),
            Path("drone_2", new(0, 3, 0), route + offsets[0]),
            Path("drone_3", new(0, 6, 0), route + offsets[1]),
        };

        var conflicts = Deconfliction.Check(paths, 2.0, 2.0).Conflicts;

        Assert.Contains(conflicts, c => (c.DroneA, c.DroneB) == ("drone_2", "drone_3"));
    }

    [Fact]
    public void Position_along_a_polyline_walks_its_segments_and_stops_at_the_end()
    {
        Vector3[] path = [new(0, 0, 0), new(0, 0, 4), new(3, 0, 4)];

        Assert.Equal(new Vector3(0, 0, 2), Deconfliction.PositionAt(path, 2));
        Assert.Equal(new Vector3(1, 0, 4), Deconfliction.PositionAt(path, 5));
        Assert.Equal(new Vector3(3, 0, 4), Deconfliction.PositionAt(path, 99));
        Assert.Equal(7.0, Deconfliction.Length(path));
    }
}
