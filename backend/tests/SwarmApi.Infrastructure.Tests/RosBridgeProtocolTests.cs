using System.Text.Json;
using SwarmApi.Domain;
using Xunit;

namespace SwarmApi.Infrastructure.Tests;

/// <summary>
/// The C# half of the rosbridge contract, checked against the same example files
/// <c>swarm_coordination/test/test_contracts.py</c> checks the Python half against.
/// </summary>
public class RosBridgeProtocolTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 22, 12, 0, 0, TimeSpan.Zero);
    private static readonly Guid ExampleMissionId = Guid.Parse("3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c");

    [Fact]
    public void Mission_payload_matches_the_contract_example()
    {
        var mission = new Mission
        {
            Id = ExampleMissionId,
            Name = "not on the wire",
            Type = MissionType.LeaderFollowerFormation,
            Formation = FormationShape.V,
            Waypoints = [new Vector3(0, 0, 5), new Vector3(10, 0, 5)],
            DroneCount = 3,
            SpacingMeters = 2.5,
            CreatedAtUtc = Now,
        };

        AssertSameJson(ContractFiles.Example("swarm_mission"), RosBridgeProtocol.MissionPayload(mission));
    }

    [Fact]
    public void Command_payload_matches_the_contract_example()
    {
        AssertSameJson(
            ContractFiles.Example("swarm_command"),
            RosBridgeProtocol.CommandPayload(SwarmCommand.ReturnToLaunch, ExampleMissionId));
    }

    [Fact]
    public void Command_payload_without_a_mission_carries_a_null_id()
    {
        using var json = JsonDocument.Parse(RosBridgeProtocol.CommandPayload(SwarmCommand.Land, null));

        Assert.Equal("land", json.RootElement.GetProperty("command").GetString());
        Assert.Equal(JsonValueKind.Null, json.RootElement.GetProperty("mission_id").ValueKind);
    }

    [Fact]
    public void State_example_parses_into_the_domain_model()
    {
        var state = RosBridgeProtocol.ParseState(ContractFiles.Example("swarm_state"), Now);

        Assert.Equal(ExampleMissionId, state.ActiveMissionId);
        Assert.False(state.ActiveMissionComplete);
        Assert.Equal(3, state.Drones.Count);

        var leader = state.Drones[0];
        Assert.Equal("drone_1", leader.Id);
        Assert.Equal(new Vector3(4.2, 0.1, 5.0), leader.Position);
        Assert.Equal(DroneStatus.InFlight, leader.Status);
        Assert.Equal(87.5, leader.BatteryPercent);
        Assert.Equal("OFFBOARD", leader.FlightMode);
        Assert.Equal(1, leader.CurrentWaypointIndex);
        Assert.Equal(Now - TimeSpan.FromSeconds(0.12), leader.LastUpdatedUtc);

        var returning = state.Drones[1];
        Assert.Equal(DroneStatus.Returning, returning.Status);
        Assert.Null(returning.BatteryPercent);

        var landed = state.Drones[2];
        Assert.Equal(DroneStatus.Landed, landed.Status);
        Assert.Null(landed.BatteryPercent);
        Assert.Equal(Now, landed.LastUpdatedUtc);
    }

    [Fact]
    public void Pre_contract_state_still_parses_with_every_unreported_field_unknown()
    {
        var state = RosBridgeProtocol.ParseState("""{"drones":[{"id":"drone_1","x":1,"y":2,"z":3}]}""", Now);

        var drone = Assert.Single(state.Drones);
        Assert.Equal(DroneStatus.Unknown, drone.Status);
        Assert.Null(drone.BatteryPercent);
        Assert.Null(drone.Armed);
        Assert.Null(state.ActiveMissionId);
    }

    [Theory]
    [InlineData("""{"version":1,"frame":"world_enu","drones":[{"id":"drone_1","y":2,"z":3}]}""")]
    [InlineData("""{"version":1,"frame":"drone_local","drones":[]}""")]
    [InlineData("""{"version":1,"frame":"world_enu","mission":{"id":"not-a-guid","complete":false},"drones":[]}""")]
    [InlineData("""[1,2,3]""")]
    [InlineData("""{"drones":[{"id":"drone_1","x":"one","y":2,"z":3}]}""")]
    [InlineData("""{"drones":""")]
    public void Malformed_state_is_a_format_error(string json)
    {
        Assert.Throws<FormatException>(() => RosBridgeProtocol.ParseState(json, Now));
    }

    [Fact]
    public void Only_state_publications_are_read_from_the_envelope()
    {
        var state = RosBridgeProtocol.Publish(RosBridgeProtocol.StateTopic, """{"drones":[]}""");
        var other = RosBridgeProtocol.Publish("/rosout", "hello");
        const string status = """{"op":"status","level":"error","msg":"no such topic"}""";

        Assert.True(RosBridgeProtocol.TryReadStateEnvelope(state, out var payload));
        Assert.Equal("""{"drones":[]}""", payload);
        Assert.False(RosBridgeProtocol.TryReadStateEnvelope(other, out _));
        Assert.False(RosBridgeProtocol.TryReadStateEnvelope(status, out _));
        Assert.ThrowsAny<JsonException>(() => RosBridgeProtocol.TryReadStateEnvelope("{not json", out _));
    }

    [Theory]
    [InlineData(null, "OFFBOARD", DroneStatus.Unknown)]
    [InlineData(false, "OFFBOARD", DroneStatus.Landed)]
    [InlineData(true, "AUTO.TAKEOFF", DroneStatus.TakingOff)]
    [InlineData(true, "AUTO.LAND", DroneStatus.Landing)]
    [InlineData(true, "AUTO.RTL", DroneStatus.Returning)]
    [InlineData(true, "AUTO.LOITER", DroneStatus.Holding)]
    [InlineData(true, "OFFBOARD", DroneStatus.InFlight)]
    [InlineData(true, null, DroneStatus.InFlight)]
    public void Px4_armed_flag_and_mode_map_to_a_status(bool? armed, string? mode, DroneStatus expected)
    {
        Assert.Equal(expected, RosBridgeProtocol.StatusFromPx4(armed, mode));
    }

    [Fact]
    public void Advertise_and_subscribe_declare_std_msgs_string()
    {
        using var advertise = JsonDocument.Parse(RosBridgeProtocol.Advertise(RosBridgeProtocol.MissionTopic));
        using var subscribe = JsonDocument.Parse(RosBridgeProtocol.Subscribe(RosBridgeProtocol.StateTopic));

        Assert.Equal("advertise", advertise.RootElement.GetProperty("op").GetString());
        Assert.Equal("std_msgs/String", advertise.RootElement.GetProperty("type").GetString());
        Assert.Equal("subscribe", subscribe.RootElement.GetProperty("op").GetString());
        Assert.Equal("/swarm/state", subscribe.RootElement.GetProperty("topic").GetString());
    }

    private static void AssertSameJson(string expected, string actual)
    {
        using var e = JsonDocument.Parse(expected);
        using var a = JsonDocument.Parse(actual);
        var difference = ContractFiles.FirstDifference(e.RootElement, a.RootElement);
        Assert.True(difference is null, $"differs from the contract example at {difference}: {actual}");
    }
}
