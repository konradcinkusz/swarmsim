using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Application.Tests;

/// <summary>
/// Missions end — by completing or by an operator stopping them — and the swarm-wide
/// overrides (return to launch, land, hold) do what they say. Driven against the simulated
/// bridge on a manual clock, so every assertion is about elapsed simulated time.
/// </summary>
public class MissionLifecycleTests
{
    private const double Spacing = 3.0;

    private static CreateMissionRequest Request(int droneCount = 2, string type = "waypoint", string? formation = null) => new(
        Name: "Lifecycle",
        Type: type,
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(10, 0, 5)],
        DroneCount: droneCount,
        SpacingMeters: Spacing,
        Formation: formation);

    private static MissionService NewService(out FakeTimeProvider time)
    {
        time = new FakeTimeProvider(new DateTimeOffset(2026, 9, 22, 12, 0, 0, TimeSpan.Zero));
        return new MissionService(new SimulatedSwarmBridge(time), MissionLimits.Default, time);
    }

    private static async Task<SwarmState> Fly(MissionService service, FakeTimeProvider time, double seconds, double step = 0.5)
    {
        for (var t = 0.0; t < seconds; t += step)
        {
            time.Advance(TimeSpan.FromSeconds(step));
            await service.GetSwarmStateAsync();
        }

        return await service.GetSwarmStateAsync();
    }

    [Fact]
    public async Task A_mission_completes_once_every_drone_has_landed()
    {
        var service = NewService(out var time);
        var mission = await service.CreateMissionAsync(Request());

        var inFlight = await Fly(service, time, 4);
        Assert.Equal(MissionStatus.Active, (await service.GetMissionAsync(mission.Id))!.Status);
        Assert.Contains(inFlight.Drones, d => d.Status is DroneStatus.InFlight or DroneStatus.TakingOff);

        var done = await Fly(service, time, 30);
        Assert.All(done.Drones, d => Assert.Equal(DroneStatus.Landed, d.Status));
        Assert.All(done.Drones, d => Assert.Equal(0, d.Position.Z));
        var finished = await service.GetMissionAsync(mission.Id);
        Assert.Equal(MissionStatus.Completed, finished!.Status);
        Assert.NotNull(finished.EndedAtUtc);
    }

    [Fact]
    public async Task Return_to_launch_brings_every_drone_back_to_its_own_pad()
    {
        var service = NewService(out var time);
        var mission = await service.CreateMissionAsync(Request());
        await Fly(service, time, 6);

        var aborted = await service.AbortMissionAsync(mission.Id, new AbortMissionRequest("rtl"));
        var returning = await Fly(service, time, 1);
        var home = await Fly(service, time, 30);

        Assert.Equal(MissionStatus.Aborted, aborted!.Status);
        Assert.Contains(returning.Drones, d => d.Status == DroneStatus.Returning);
        for (var i = 0; i < home.Drones.Count; i++)
        {
            var pad = new Vector3(0, i * Spacing, 0);
            Assert.Equal(DroneStatus.Landed, home.Drones[i].Status);
            Assert.True(home.Drones[i].Position.DistanceTo(pad) < 0.5, $"{home.Drones[i].Id} landed at {home.Drones[i].Position}, not its pad {pad}");
        }

        Assert.Null(home.ActiveMissionId);
    }

    [Fact]
    public async Task Land_all_descends_in_place_and_ends_the_active_mission()
    {
        var service = NewService(out var time);
        var mission = await service.CreateMissionAsync(Request());
        var before = await Fly(service, time, 6);

        await service.LandAllAsync();
        var landed = await Fly(service, time, 10);

        for (var i = 0; i < landed.Drones.Count; i++)
        {
            Assert.Equal(DroneStatus.Landed, landed.Drones[i].Status);
            Assert.Equal(before.Drones[i].Position.X, landed.Drones[i].Position.X, precision: 1);
            Assert.Equal(before.Drones[i].Position.Y, landed.Drones[i].Position.Y, precision: 1);
        }

        Assert.Equal(MissionStatus.Aborted, (await service.GetMissionAsync(mission.Id))!.Status);
    }

    [Fact]
    public async Task Hold_stops_the_swarm_in_the_air()
    {
        var service = NewService(out var time);
        var mission = await service.CreateMissionAsync(Request());
        await Fly(service, time, 6);

        await service.AbortMissionAsync(mission.Id, new AbortMissionRequest("hold"));
        var first = await Fly(service, time, 1);
        var later = await Fly(service, time, 10);

        Assert.All(later.Drones, d => Assert.Equal(DroneStatus.Holding, d.Status));
        for (var i = 0; i < later.Drones.Count; i++)
        {
            Assert.Equal(first.Drones[i].Position, later.Drones[i].Position);
            Assert.True(later.Drones[i].Position.Z > 1);
        }
    }

    [Fact]
    public async Task Aborting_a_finished_mission_is_a_conflict_and_an_unknown_one_is_not_found()
    {
        var service = NewService(out var time);
        var mission = await service.CreateMissionAsync(Request());
        await Fly(service, time, 40);

        await Assert.ThrowsAsync<MissionStateException>(() => service.AbortMissionAsync(mission.Id, null));
        Assert.Null(await service.AbortMissionAsync(Guid.NewGuid(), null));
    }

    [Fact]
    public async Task An_unknown_abort_action_is_rejected_before_anything_is_sent()
    {
        var service = NewService(out var time);
        var mission = await service.CreateMissionAsync(Request());
        await Fly(service, time, 2);

        await Assert.ThrowsAsync<MissionValidationException>(() =>
            service.AbortMissionAsync(mission.Id, new AbortMissionRequest("self-destruct")));
        Assert.Equal(MissionStatus.Active, (await service.GetMissionAsync(mission.Id))!.Status);
    }

    [Fact]
    public async Task A_new_mission_supersedes_the_one_still_flying()
    {
        var service = NewService(out var time);
        var first = await service.CreateMissionAsync(Request());
        await Fly(service, time, 3);

        var second = await service.CreateMissionAsync(Request(droneCount: 3));

        Assert.Equal(MissionStatus.Aborted, (await service.GetMissionAsync(first.Id))!.Status);
        Assert.Equal(MissionStatus.Active, (await service.GetMissionAsync(second.Id))!.Status);
    }

    [Fact]
    public async Task Battery_drain_follows_elapsed_time_not_how_often_state_is_read()
    {
        // A long leg, so neither drone lands inside the window: this measures drain alone.
        var longLeg = Request(droneCount: 1) with { Waypoints = [new WaypointDto(0, 0, 5), new WaypointDto(200, 0, 5)] };
        var polledOften = NewService(out var timeA);
        var polledOnce = NewService(out var timeB);
        await polledOften.CreateMissionAsync(longLeg);
        await polledOnce.CreateMissionAsync(longLeg);

        var often = await Fly(polledOften, timeA, 10, step: 0.1);
        timeB.Advance(TimeSpan.FromSeconds(10));
        var once = await polledOnce.GetSwarmStateAsync();

        Assert.Equal(often.Drones[0].BatteryPercent!.Value, once.Drones[0].BatteryPercent!.Value, precision: 2);
        Assert.Equal(99.5, once.Drones[0].BatteryPercent!.Value, precision: 2); // 10 s at 0.05 %/s
    }

    [Fact]
    public async Task A_v_formation_puts_followers_on_both_sides_of_the_leader()
    {
        var service = NewService(out var time);
        await service.CreateMissionAsync(Request(droneCount: 3, type: "formation", formation: "v"));

        var state = await Fly(service, time, 3);
        var leader = state.Drones[0].Position;

        Assert.True(state.Drones[1].Position.Y > leader.Y + 1, "first follower should sit to the left (+y)");
        Assert.True(state.Drones[2].Position.Y < leader.Y - 1, "second follower should sit to the right (-y)");
    }

    [Fact]
    public async Task A_swarm_that_cannot_be_reached_rejects_the_mission_and_logs_nothing()
    {
        var service = new MissionService(new UnreachableBridge());

        await Assert.ThrowsAsync<SwarmUnavailableException>(() => service.CreateMissionAsync(Request()));
        await Assert.ThrowsAsync<SwarmUnavailableException>(() => service.LandAllAsync());
    }

    private sealed class UnreachableBridge : ISwarmBridge
    {
        public SwarmBridgeMode Mode => SwarmBridgeMode.Disconnected;

        public DateTimeOffset? LastStateReceivedUtc => null;

        public Task DispatchMissionAsync(Mission mission, CancellationToken cancellationToken = default) =>
            throw new SwarmUnavailableException("rosbridge is down");

        public Task SendCommandAsync(SwarmCommand command, Guid? missionId, CancellationToken cancellationToken = default) =>
            throw new SwarmUnavailableException("rosbridge is down");

        public Task<SwarmState> GetStateAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new SwarmState { Drones = [], TimestampUtc = DateTimeOffset.UtcNow, BridgeMode = Mode });
    }
}
