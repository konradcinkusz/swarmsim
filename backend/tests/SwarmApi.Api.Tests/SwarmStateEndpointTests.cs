using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;
using Xunit;

namespace SwarmApi.Api.Tests;

public class SwarmStateEndpointTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    [Fact]
    public async Task Get_swarm_state_reflects_a_dispatched_mission()
    {
        var client = factory.CreateClient();
        var request = new CreateMissionRequest(
            Name: "State check",
            Type: "waypoint",
            Waypoints: [new WaypointDto(0, 0, 5)],
            DroneCount: 2,
            SpacingMeters: 2.0);

        var created = await (await client.PostAsJsonAsync("/api/missions", request))
            .Content.ReadFromJsonAsync<Mission>(TestJson.Options);

        var response = await client.GetAsync("/api/swarm/state");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var state = await response.Content.ReadFromJsonAsync<SwarmState>(TestJson.Options);
        Assert.NotNull(state);
        Assert.Equal(2, state!.Drones.Count);
        Assert.Equal(created!.Id, state.ActiveMissionId);
        Assert.Equal(SwarmBridgeMode.Simulated, state.BridgeMode);
    }

    [Fact]
    public async Task Get_swarm_state_before_any_mission_returns_an_empty_swarm()
    {
        // A fresh factory instance: no mission has been dispatched on this client yet.
        using var freshFactory = new WebApplicationFactory<Program>();
        var client = freshFactory.CreateClient();

        var response = await client.GetAsync("/api/swarm/state");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var state = await response.Content.ReadFromJsonAsync<SwarmState>(TestJson.Options);
        Assert.NotNull(state);
        Assert.Empty(state!.Drones);
        Assert.Null(state.ActiveMissionId);
    }
}
