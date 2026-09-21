using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Application.Tests;

public class MissionServiceTests
{
    private static CreateMissionRequest WaypointRequest(int droneCount = 2) => new(
        Name: "Line sweep",
        Type: "waypoint",
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(10, 0, 5)],
        DroneCount: droneCount,
        SpacingMeters: 3.0);

    private static MissionService NewService(out FakeTimeProvider time)
    {
        time = new FakeTimeProvider(DateTimeOffset.UtcNow);
        return new MissionService(new SimulatedSwarmBridge(time));
    }

    [Fact]
    public async Task CreateMissionAsync_validates_before_dispatching()
    {
        var service = NewService(out _);
        var invalid = WaypointRequest() with { DroneCount = 0 };

        await Assert.ThrowsAsync<MissionValidationException>(() => service.CreateMissionAsync(invalid));
    }

    [Fact]
    public async Task Dispatched_mission_is_retrievable_by_id()
    {
        var service = NewService(out _);

        var mission = await service.CreateMissionAsync(WaypointRequest());
        var fetched = await service.GetMissionAsync(mission.Id);

        Assert.NotNull(fetched);
        Assert.Equal(mission.Id, fetched!.Id);
        Assert.Equal(MissionType.WaypointFollow, fetched.Type);
    }

    [Fact]
    public async Task GetMissionAsync_returns_null_for_unknown_id()
    {
        var service = NewService(out _);

        Assert.Null(await service.GetMissionAsync(Guid.NewGuid()));
    }

    [Fact]
    public async Task GetSwarmStateAsync_spawns_the_requested_number_of_drones()
    {
        var service = NewService(out _);

        await service.CreateMissionAsync(WaypointRequest(droneCount: 4));
        var state = await service.GetSwarmStateAsync();

        Assert.Equal(4, state.Drones.Count);
        Assert.Equal(SwarmBridgeMode.Simulated, state.BridgeMode);
    }

    [Fact]
    public async Task Drones_advance_towards_their_waypoints_over_elapsed_time()
    {
        var service = NewService(out var time);

        await service.CreateMissionAsync(WaypointRequest(droneCount: 1));
        var before = (await service.GetSwarmStateAsync()).Drones[0].Position;

        time.Advance(TimeSpan.FromSeconds(2));
        var after = (await service.GetSwarmStateAsync()).Drones[0].Position;

        Assert.True(after.DistanceTo(before) > 0, "drone did not move over 2 elapsed seconds");
    }

    [Fact]
    public async Task Waypoint_mission_lands_every_drone_once_its_path_completes()
    {
        var service = NewService(out var time);
        await service.CreateMissionAsync(WaypointRequest(droneCount: 2));

        // Total path length (5m + 10m) at 2 m/s completes well within 30s.
        for (var i = 0; i < 30; i++)
        {
            time.Advance(TimeSpan.FromSeconds(1));
            await service.GetSwarmStateAsync();
        }

        var state = await service.GetSwarmStateAsync();
        Assert.All(state.Drones, d => Assert.Equal(DroneStatus.Landed, d.Status));
    }

    [Fact]
    public async Task Formation_mission_keeps_followers_close_to_the_leader()
    {
        var service = NewService(out var time);
        var request = WaypointRequest(droneCount: 3) with { Type = "formation" };
        await service.CreateMissionAsync(request);

        for (var i = 0; i < 20; i++)
        {
            time.Advance(TimeSpan.FromSeconds(1));
            await service.GetSwarmStateAsync();
        }

        var state = await service.GetSwarmStateAsync();
        var leader = state.Drones.Single(d => d.Id == "drone_1").Position;
        Assert.All(
            state.Drones.Where(d => d.Id != "drone_1"),
            follower => Assert.True(follower.Position.DistanceTo(leader) < 10.0));
    }

    [Fact]
    public async Task No_collision_across_a_three_drone_waypoint_swarm()
    {
        var service = NewService(out var time);
        await service.CreateMissionAsync(WaypointRequest(droneCount: 3));

        for (var i = 0; i < 10; i++)
        {
            time.Advance(TimeSpan.FromMilliseconds(500));
            var state = await service.GetSwarmStateAsync();
            var positions = state.Drones.Select(d => d.Position).ToList();

            // Drones fly on parallel lanes >= 3m apart (SpacingMeters), so they must
            // never end up closer than 1m — M2's no-collision acceptance criterion.
            Assert.False(Formation.HasCollision(positions, minDistanceMeters: 1.0));
        }
    }
}
