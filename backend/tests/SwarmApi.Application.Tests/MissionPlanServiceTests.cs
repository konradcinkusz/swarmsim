using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Application.Tests;

/// <summary>The write gate (docs/adr/0009), enforced by the service whatever the caller does.</summary>
public class MissionPlanServiceTests
{
    private static CreateMissionRequest Request(string type = "waypoint", string? formation = null, int drones = 2) => new(
        Name: "Gate",
        Type: type,
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(20, 0, 5)],
        DroneCount: drones,
        SpacingMeters: 3.0,
        Formation: formation);

    private static (MissionPlanService Plans, MissionService Missions, FakeTimeProvider Time) NewServices()
    {
        var time = new FakeTimeProvider(new DateTimeOffset(2026, 9, 22, 12, 0, 0, TimeSpan.Zero));
        var bridge = new SimulatedSwarmBridge(time);
        var missions = new MissionService(bridge, MissionLimits.Default, time);
        return (new MissionPlanService(missions, bridge, MissionLimits.Default, PlanningOptions.Default, time), missions, time);
    }

    [Fact]
    public async Task A_plan_waits_for_approval_with_a_preview_of_every_drones_path()
    {
        var (plans, _, _) = NewServices();

        var plan = await plans.CreatePlanAsync(Request(), "agent");

        Assert.Equal(MissionPlanStatus.PendingApproval, plan.Status);
        Assert.Equal(["drone_1", "drone_2"], plan.Preview.Drones.Select(d => d.DroneId));
        Assert.Equal(new Vector3(0, 3, 0), plan.Preview.Drones[1].Path[0]); // unreported: on its pad
        Assert.Equal(new Vector3(20, 3, 5), plan.Preview.Drones[1].Path[^1]); // its own lane
        Assert.Empty(plan.Preview.Conflicts);
        Assert.Contains(plan.Preview.Assumptions, a => a.Contains("not reported", StringComparison.Ordinal));
    }

    [Fact]
    public async Task A_plan_whose_paths_conflict_cannot_be_approved()
    {
        var (plans, _, _) = NewServices();

        var plan = await plans.CreatePlanAsync(Request("formation", "v", drones: 3), "agent");

        Assert.Equal(MissionPlanStatus.Conflicted, plan.Status);
        Assert.NotEmpty(plan.Preview.Conflicts);
        Assert.Throws<PlanStateException>(() => plans.Approve(plan.Id, "operator"));
    }

    [Fact]
    public async Task Approval_returns_a_code_once_and_only_the_code_dispatches_the_plan_once()
    {
        var (plans, missions, _) = NewServices();
        var plan = await plans.CreatePlanAsync(Request(), "agent");

        var approval = plans.Approve(plan.Id, "operator")!;
        Assert.Equal(32, approval.ApprovalCode.Length);
        Assert.Throws<PlanStateException>(() => plans.Approve(plan.Id, "operator"));

        await Assert.ThrowsAsync<ApprovalRefusedException>(() => plans.DispatchAsync(plan.Id, "not-the-code"));
        await Assert.ThrowsAsync<ApprovalRefusedException>(() => plans.DispatchAsync(plan.Id, null));
        var mission = await plans.DispatchAsync(plan.Id, approval.ApprovalCode);

        Assert.NotNull(mission);
        Assert.Equal(MissionStatus.Active, (await missions.GetMissionAsync(mission!.Id))!.Status);
        Assert.Equal(MissionPlanStatus.Dispatched, plans.GetPlan(plan.Id)!.Status);
        Assert.Equal(mission.Id, plans.GetPlan(plan.Id)!.MissionId);
        await Assert.ThrowsAsync<PlanStateException>(() => plans.DispatchAsync(plan.Id, approval.ApprovalCode));
    }

    [Fact]
    public async Task What_was_approved_is_exactly_what_flies()
    {
        var (plans, _, _) = NewServices();
        var plan = await plans.CreatePlanAsync(Request(drones: 3), "agent");
        var approval = plans.Approve(plan.Id, "operator")!;

        var mission = (await plans.DispatchAsync(plan.Id, approval.ApprovalCode))!;

        Assert.Equal(plan.Waypoints, mission.Waypoints);
        Assert.Equal((plan.DroneCount, plan.SpacingMeters, plan.Type), (mission.DroneCount, mission.SpacingMeters, mission.Type));
    }

    [Fact]
    public async Task The_identity_that_proposed_a_plan_cannot_approve_it()
    {
        var (plans, _, _) = NewServices();
        var plan = await plans.CreatePlanAsync(Request(), "agent");

        Assert.Throws<ApprovalRefusedException>(() => plans.Approve(plan.Id, "agent"));
        Assert.NotNull(plans.Approve(plan.Id, "operator"));
    }

    [Fact]
    public async Task An_undecided_plan_and_an_unused_approval_both_expire()
    {
        var (plans, _, time) = NewServices();
        var undecided = await plans.CreatePlanAsync(Request(), "agent");
        var approved = await plans.CreatePlanAsync(Request(), "agent");
        var approval = plans.Approve(approved.Id, "operator")!;

        time.Advance(TimeSpan.FromMinutes(PlanningOptions.Default.ApprovalValidityMinutes + 1));
        Assert.Equal(MissionPlanStatus.Expired, plans.GetPlan(approved.Id)!.Status);
        await Assert.ThrowsAsync<PlanStateException>(() => plans.DispatchAsync(approved.Id, approval.ApprovalCode));

        time.Advance(TimeSpan.FromMinutes(PlanningOptions.Default.DecisionWindowMinutes));
        Assert.Equal(MissionPlanStatus.Expired, plans.GetPlan(undecided.Id)!.Status);
        Assert.Throws<PlanStateException>(() => plans.Approve(undecided.Id, "operator"));
    }

    [Fact]
    public async Task A_rejected_plan_stays_rejected_and_its_approval_is_void()
    {
        var (plans, _, _) = NewServices();
        var plan = await plans.CreatePlanAsync(Request(), "agent");
        var approval = plans.Approve(plan.Id, "operator")!;

        Assert.Equal(MissionPlanStatus.Rejected, plans.Reject(plan.Id, "operator")!.Status);

        await Assert.ThrowsAsync<PlanStateException>(() => plans.DispatchAsync(plan.Id, approval.ApprovalCode));
        Assert.Throws<PlanStateException>(() => plans.Reject(plan.Id, "operator"));
    }

    [Fact]
    public async Task An_unknown_plan_is_null_everywhere()
    {
        var (plans, _, _) = NewServices();
        var unknown = Guid.NewGuid();

        Assert.Null(plans.GetPlan(unknown));
        Assert.Null(plans.Approve(unknown, "operator"));
        Assert.Null(plans.Reject(unknown, "operator"));
        Assert.Null(await plans.DispatchAsync(unknown, "code"));
    }

    [Fact]
    public async Task A_plan_is_validated_against_the_same_envelope_as_a_mission()
    {
        var (plans, _, _) = NewServices();

        await Assert.ThrowsAsync<MissionValidationException>(() => plans.CreatePlanAsync(Request(drones: 99), "agent"));
    }

    [Fact]
    public async Task Drones_the_swarm_reports_start_from_where_they_are()
    {
        var (plans, missions, time) = NewServices();
        await missions.CreateMissionAsync(Request());
        time.Advance(TimeSpan.FromSeconds(60));
        var state = await missions.GetSwarmStateAsync();

        var plan = await plans.CreatePlanAsync(Request(), "agent");

        Assert.Equal(state.Drones[0].Position, plan.Preview.Drones[0].Path[0]);
    }

    [Fact]
    public void Approval_codes_are_random_and_only_their_hash_matches()
    {
        var codes = Enumerable.Range(0, 200).Select(_ => ApprovalCode.New()).ToHashSet();
        var code = codes.First();

        Assert.Equal(200, codes.Count);
        Assert.All(codes, c => Assert.Matches("^[A-Za-z0-9_-]{32}$", c));
        Assert.True(ApprovalCode.Matches(code, ApprovalCode.Hash(code)));
        Assert.False(ApprovalCode.Matches(code + "x", ApprovalCode.Hash(code)));
        Assert.False(ApprovalCode.Matches(null, ApprovalCode.Hash(code)));
    }
}
