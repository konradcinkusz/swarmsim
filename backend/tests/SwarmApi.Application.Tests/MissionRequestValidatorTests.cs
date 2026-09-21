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
}
