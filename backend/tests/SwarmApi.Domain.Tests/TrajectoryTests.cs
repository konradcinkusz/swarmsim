using SwarmApi.Domain;
using Xunit;

namespace SwarmApi.Domain.Tests;

public class TrajectoryTests
{
    [Fact]
    public void Vector_addition_and_subtraction()
    {
        var a = new Vector3(1, 2, 3);
        var b = new Vector3(4, 0, -1);

        Assert.Equal(new Vector3(5, 2, 2), a + b);
        Assert.Equal(new Vector3(-3, 2, 4), a - b);
    }

    [Fact]
    public void Norm_and_distance()
    {
        var origin = Vector3.Zero;
        var p = new Vector3(3, 4, 0);

        Assert.Equal(5.0, p.Norm(), precision: 6);
        Assert.Equal(5.0, origin.DistanceTo(p), precision: 6);
    }

    [Fact]
    public void StepTowards_reaches_target_exactly_within_max_step()
    {
        var current = Vector3.Zero;
        var target = new Vector3(0.3, 0, 0);

        var result = Trajectory.StepTowards(current, target, maxStep: 0.5);

        Assert.Equal(target, result);
    }

    [Fact]
    public void StepTowards_moves_partway_when_farther_than_max_step()
    {
        var current = Vector3.Zero;
        var target = new Vector3(10, 0, 0);

        var result = Trajectory.StepTowards(current, target, maxStep: 1.0);

        Assert.Equal(1.0, result.DistanceTo(current), precision: 6);
        Assert.Equal(9.0, result.DistanceTo(target), precision: 6);
    }

    [Fact]
    public void StepTowards_converges_in_a_finite_number_of_steps()
    {
        var current = Vector3.Zero;
        var target = new Vector3(5, 5, 0);
        const double maxStep = 0.7;
        var steps = 0;

        while (current != target)
        {
            current = Trajectory.StepTowards(current, target, maxStep);
            steps++;
            Assert.True(steps < 1000, "did not converge");
        }

        Assert.Equal(target, current);
        Assert.Equal((int)Math.Ceiling(target.Norm() / maxStep), steps);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    public void StepTowards_rejects_non_positive_step(double maxStep)
    {
        Assert.Throws<ArgumentOutOfRangeException>(
            () => Trajectory.StepTowards(Vector3.Zero, new Vector3(1, 0, 0), maxStep));
    }
}
