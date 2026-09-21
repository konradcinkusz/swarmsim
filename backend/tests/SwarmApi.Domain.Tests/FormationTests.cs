using SwarmApi.Domain;
using Xunit;

namespace SwarmApi.Domain.Tests;

public class FormationTests
{
    [Fact]
    public void Line_offsets_are_spaced_behind_the_leader()
    {
        var offsets = Formation.Line(3, spacingMeters: 2.0);

        Assert.Equal(
            [new Vector3(-2, 0, 0), new Vector3(-4, 0, 0), new Vector3(-6, 0, 0)],
            offsets);
    }

    [Fact]
    public void Line_of_zero_count_is_empty()
    {
        Assert.Empty(Formation.Line(0, 2.0));
    }

    [Fact]
    public void Line_rejects_negative_count()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() => Formation.Line(-1, 2.0));
    }

    [Fact]
    public void MinSeparation_is_null_for_fewer_than_two_positions()
    {
        Assert.Null(Formation.MinSeparation([]));
        Assert.Null(Formation.MinSeparation([Vector3.Zero]));
    }

    [Fact]
    public void MinSeparation_finds_the_closest_pair()
    {
        Vector3[] positions = [new(0, 0, 0), new(10, 0, 0), new(0, 1, 0)];

        Assert.Equal(1.0, Formation.MinSeparation(positions)!.Value, precision: 6);
    }

    [Theory]
    [InlineData(0.5, false)]
    [InlineData(1.5, true)]
    public void HasCollision_against_a_three_drone_line_formation(double minDistance, bool expected)
    {
        var leader = new Vector3(0, 0, 5);
        var offsets = Formation.Line(2, spacingMeters: 1.0);
        List<Vector3> positions = [leader, .. offsets.Select(o => leader + o)];

        Assert.Equal(expected, Formation.HasCollision(positions, minDistance));
    }

    [Theory]
    [MemberData(nameof(FormationStartingPoints))]
    public void No_collision_across_three_different_starting_points(Vector3 start)
    {
        var offsets = Formation.Line(4, spacingMeters: 2.0);
        List<Vector3> positions = [start, .. offsets.Select(o => start + o)];

        Assert.False(Formation.HasCollision(positions, minDistanceMeters: 1.0));
    }

    public static TheoryData<Vector3> FormationStartingPoints() =>
        new() { new Vector3(0, 0, 5), new Vector3(100, -50, 20), new Vector3(-30, 30, 5) };
}
