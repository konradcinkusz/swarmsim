using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using Xunit;

namespace SwarmApi.Application.Tests;

public class MissionRequestValidatorTests
{
    private static CreateMissionRequest ValidRequest() => new(
        Name: "Perimeter sweep",
        Type: "waypoint",
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(10, 0, 5)],
        DroneCount: 3,
        SpacingMeters: 2.0);

    [Fact]
    public void Accepts_a_valid_request()
    {
        MissionRequestValidator.Validate(ValidRequest()); // does not throw
    }

    [Fact]
    public void Rejects_blank_name()
    {
        var request = ValidRequest() with { Name = "  " };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("Name"));
    }

    [Theory]
    [InlineData("orbit")]
    [InlineData("")]
    public void Rejects_unknown_mission_type(string type)
    {
        var request = ValidRequest() with { Type = type };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("Type"));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(6)]
    public void Rejects_drone_count_outside_the_M1_scope(int droneCount)
    {
        var request = ValidRequest() with { DroneCount = droneCount };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("DroneCount"));
    }

    [Fact]
    public void Rejects_empty_waypoints()
    {
        var request = ValidRequest() with { Waypoints = [] };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("waypoint"));
    }

    [Fact]
    public void Rejects_non_positive_spacing()
    {
        var request = ValidRequest() with { SpacingMeters = 0 };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("SpacingMeters"));
    }

    [Fact]
    public void Reports_every_failing_rule_at_once()
    {
        var request = new CreateMissionRequest(
            Name: "", Type: "orbit", Waypoints: [], DroneCount: 0, SpacingMeters: -1);

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Equal(5, ex.Errors.Count);
    }

    [Theory]
    [InlineData(double.NaN, 0, 5)]
    [InlineData(0, double.PositiveInfinity, 5)]
    [InlineData(0, 0, double.NegativeInfinity)]
    public void Rejects_non_finite_coordinates(double x, double y, double z)
    {
        var request = ValidRequest() with { Waypoints = [new WaypointDto(x, y, z)] };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("finite"));
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-3)]
    [InlineData(120.5)]
    public void Rejects_altitudes_at_or_below_ground_and_above_the_ceiling(double z)
    {
        var request = ValidRequest() with { Waypoints = [new WaypointDto(0, 0, z)] };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("altitude"));
    }

    [Fact]
    public void Rejects_a_waypoint_outside_the_geofence()
    {
        var request = ValidRequest() with { Waypoints = [new WaypointDto(800, 700, 10)] };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("geofence"));
    }

    [Fact]
    public void Rejects_more_waypoints_than_the_limit()
    {
        var request = ValidRequest() with
        {
            Waypoints = Enumerable.Range(0, 101).Select(i => new WaypointDto(i % 10, 0, 5)).ToList(),
        };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("waypoints are allowed"));
    }

    [Theory]
    [InlineData("circle")]
    [InlineData("V")]
    public void Rejects_an_unknown_formation(string formation)
    {
        var request = ValidRequest() with { Type = "formation", Formation = formation };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("Formation"));
    }

    [Fact]
    public void Rejects_an_overlong_name()
    {
        var request = ValidRequest() with { Name = new string('x', 201) };

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.Contains(ex.Errors, e => e.Contains("Name"));
    }

    [Fact]
    public void Configured_limits_replace_the_defaults()
    {
        var limits = new MissionLimits { MaxDroneCount = 10, MaxAltitudeMeters = 30 };
        var many = ValidRequest() with { DroneCount = 8 };
        var high = ValidRequest() with { Waypoints = [new WaypointDto(0, 0, 40)] };

        MissionRequestValidator.Validate(many, limits); // does not throw
        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(high, limits));
        Assert.Contains(ex.Errors, e => e.Contains("30"));
    }

    [Fact]
    public void Reports_the_new_rules_alongside_the_old_ones()
    {
        var request = new CreateMissionRequest("", "orbit", [new WaypointDto(0, 0, -1)], 0, -1, "circle");

        var ex = Assert.Throws<MissionValidationException>(() => MissionRequestValidator.Validate(request));
        Assert.True(ex.Errors.Count >= 6, string.Join(" | ", ex.Errors));
    }
}
