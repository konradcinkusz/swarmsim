using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>The write gate over HTTP (docs/adr/0009): propose, preview, approve, dispatch once.</summary>
public class MissionPlanEndpointTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private static CreateMissionRequest Request(string type = "waypoint", string? formation = null, int drones = 2) => new(
        Name: "Gate over HTTP",
        Type: type,
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(20, 0, 5)],
        DroneCount: drones,
        SpacingMeters: 3.0,
        Formation: formation);

    private async Task<MissionPlanView> Propose(HttpClient client, CreateMissionRequest request)
    {
        var response = await client.PostAsJsonAsync("/api/mission-plans", request);
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await response.Content.ReadFromJsonAsync<MissionPlanView>(TestJson.Options))!;
    }

    [Fact]
    public async Task A_plan_is_proposed_approved_and_dispatched_once_with_its_code()
    {
        var client = factory.CreateClient();
        var plan = await Propose(client, Request());
        Assert.Equal(MissionPlanStatus.PendingApproval, plan.Status);

        var approve = await client.PostAsync($"/api/mission-plans/{plan.Id}/approve", null);
        Assert.Equal(HttpStatusCode.OK, approve.StatusCode);
        var approval = (await approve.Content.ReadFromJsonAsync<PlanApproval>(TestJson.Options))!;

        // The code is in the approval response and nowhere else.
        var read = await client.GetStringAsync($"/api/mission-plans/{plan.Id}");
        Assert.DoesNotContain(approval.ApprovalCode, read, StringComparison.Ordinal);
        Assert.DoesNotContain("hash", read, StringComparison.OrdinalIgnoreCase);

        var dispatch = await client.PostAsJsonAsync(
            $"/api/mission-plans/{plan.Id}/dispatch", new DispatchPlanRequest(approval.ApprovalCode));
        Assert.Equal(HttpStatusCode.Created, dispatch.StatusCode);
        var mission = (await dispatch.Content.ReadFromJsonAsync<Mission>(TestJson.Options))!;
        Assert.Equal($"/api/missions/{mission.Id}", dispatch.Headers.Location!.OriginalString);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync($"/api/missions/{mission.Id}")).StatusCode);

        var again = await client.PostAsJsonAsync(
            $"/api/mission-plans/{plan.Id}/dispatch", new DispatchPlanRequest(approval.ApprovalCode));
        Assert.Equal(HttpStatusCode.Conflict, again.StatusCode);
    }

    [Fact]
    public async Task Dispatch_without_the_right_code_is_forbidden_and_an_unapproved_plan_is_a_conflict()
    {
        var client = factory.CreateClient();
        var plan = await Propose(client, Request());

        var unapproved = await client.PostAsJsonAsync(
            $"/api/mission-plans/{plan.Id}/dispatch", new DispatchPlanRequest("anything"));
        Assert.Equal(HttpStatusCode.Conflict, unapproved.StatusCode);

        await client.PostAsync($"/api/mission-plans/{plan.Id}/approve", null);
        var wrong = await client.PostAsJsonAsync(
            $"/api/mission-plans/{plan.Id}/dispatch", new DispatchPlanRequest("wrong"));
        var missing = await client.PostAsync($"/api/mission-plans/{plan.Id}/dispatch", null);

        Assert.Equal(HttpStatusCode.Forbidden, wrong.StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, missing.StatusCode);
    }

    [Fact]
    public async Task A_conflicted_plan_shows_its_conflicts_and_approving_it_is_a_conflict()
    {
        var client = factory.CreateClient();
        var plan = await Propose(client, Request("formation", "v", drones: 3));

        Assert.Equal(MissionPlanStatus.Conflicted, plan.Status);
        Assert.Contains(plan.Preview.Conflicts, c => (c.DroneA, c.DroneB) == ("drone_2", "drone_3"));
        var approve = await client.PostAsync($"/api/mission-plans/{plan.Id}/approve", null);
        Assert.Equal(HttpStatusCode.Conflict, approve.StatusCode);
        Assert.Contains("conflict", await approve.Content.ReadAsStringAsync(), StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task Plans_are_listed_newest_first_and_rejection_is_final()
    {
        var client = factory.CreateClient();
        var first = await Propose(client, Request());
        var second = await Propose(client, Request());

        var rejected = await client.PostAsync($"/api/mission-plans/{first.Id}/reject", null);
        var list = await client.GetFromJsonAsync<List<MissionPlanView>>("/api/mission-plans?limit=500", TestJson.Options);

        Assert.Equal(HttpStatusCode.OK, rejected.StatusCode);
        Assert.Equal(second.Id, list![0].Id);
        Assert.Equal(MissionPlanStatus.Rejected, list.Single(p => p.Id == first.Id).Status);
        Assert.Equal(HttpStatusCode.Conflict, (await client.PostAsync($"/api/mission-plans/{first.Id}/approve", null)).StatusCode);
    }

    [Fact]
    public async Task Unknown_plans_are_404_and_an_invalid_proposal_is_400()
    {
        var client = factory.CreateClient();
        var unknown = Guid.NewGuid();

        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync($"/api/mission-plans/{unknown}")).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await client.PostAsync($"/api/mission-plans/{unknown}/approve", null)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await client.PostAsync($"/api/mission-plans/{unknown}/reject", null)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await client.PostAsJsonAsync(
            $"/api/mission-plans/{unknown}/dispatch", new DispatchPlanRequest("x"))).StatusCode);
        var invalid = await client.PostAsJsonAsync("/api/mission-plans", Request(drones: 99));
        Assert.Equal(HttpStatusCode.BadRequest, invalid.StatusCode);
    }

    [Fact]
    public async Task The_preview_speaks_the_same_json_as_everything_else()
    {
        var client = factory.CreateClient();
        var response = await client.PostAsJsonAsync("/api/mission-plans", Request());

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        var root = document.RootElement;
        Assert.Equal("PendingApproval", root.GetProperty("status").GetString());
        Assert.Equal("WaypointFollow", root.GetProperty("type").GetString());
        var drone = root.GetProperty("preview").GetProperty("drones")[0];
        Assert.Equal("drone_1", drone.GetProperty("droneId").GetString());
        Assert.True(drone.GetProperty("path").GetArrayLength() >= 2);
    }
}
