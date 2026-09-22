using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;
using Xunit;

namespace SwarmApi.Api.Tests;

public class MissionsEndpointTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private static CreateMissionRequest ValidRequest() => new(
        Name: "Integration test sweep",
        Type: "waypoint",
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(10, 0, 5)],
        DroneCount: 3,
        SpacingMeters: 2.0);

    [Fact]
    public async Task Post_missions_with_a_valid_request_returns_201_with_the_created_mission()
    {
        var client = factory.CreateClient();

        var response = await client.PostAsJsonAsync("/api/missions", ValidRequest());

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var mission = await response.Content.ReadFromJsonAsync<Mission>(TestJson.Options);
        Assert.NotNull(mission);
        Assert.Equal("Integration test sweep", mission!.Name);
        Assert.Equal(3, mission.DroneCount);
        Assert.NotEqual(Guid.Empty, mission.Id);
    }

    [Fact]
    public async Task Post_missions_with_an_invalid_request_returns_400_with_validation_errors()
    {
        var client = factory.CreateClient();
        var invalid = ValidRequest() with { DroneCount = 0, Name = "" };

        var response = await client.PostAsJsonAsync("/api/missions", invalid);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        Assert.Contains("DroneCount", body);
    }

    [Fact]
    public async Task Get_missions_by_id_returns_a_previously_created_mission()
    {
        var client = factory.CreateClient();
        var created = await (await client.PostAsJsonAsync("/api/missions", ValidRequest()))
            .Content.ReadFromJsonAsync<Mission>(TestJson.Options);

        var response = await client.GetAsync($"/api/missions/{created!.Id}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var fetched = await response.Content.ReadFromJsonAsync<Mission>(TestJson.Options);
        Assert.Equal(created.Id, fetched!.Id);
    }

    [Fact]
    public async Task Get_missions_by_unknown_id_returns_404()
    {
        var client = factory.CreateClient();

        var response = await client.GetAsync($"/api/missions/{Guid.NewGuid()}");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task Aborting_an_active_mission_returns_it_as_aborted_and_a_second_abort_conflicts()
    {
        var client = factory.CreateClient();
        var created = await (await client.PostAsJsonAsync("/api/missions", ValidRequest()))
            .Content.ReadFromJsonAsync<Mission>(TestJson.Options);

        var abort = await client.PostAsJsonAsync($"/api/missions/{created!.Id}/abort", new AbortMissionRequest("land"));
        var again = await client.PostAsync($"/api/missions/{created.Id}/abort", content: null);
        var fetched = await client.GetFromJsonAsync<Mission>($"/api/missions/{created.Id}", TestJson.Options);

        Assert.Equal(HttpStatusCode.OK, abort.StatusCode);
        Assert.Equal(MissionStatus.Aborted, (await abort.Content.ReadFromJsonAsync<Mission>(TestJson.Options))!.Status);
        Assert.Equal(HttpStatusCode.Conflict, again.StatusCode);
        Assert.Equal(MissionStatus.Aborted, fetched!.Status);
    }

    [Fact]
    public async Task Aborting_with_no_body_uses_return_to_launch()
    {
        var client = factory.CreateClient();
        var created = await (await client.PostAsJsonAsync("/api/missions", ValidRequest()))
            .Content.ReadFromJsonAsync<Mission>(TestJson.Options);

        var abort = await client.PostAsync($"/api/missions/{created!.Id}/abort", content: null);

        Assert.Equal(HttpStatusCode.OK, abort.StatusCode);
    }

    [Fact]
    public async Task Aborting_an_unknown_mission_is_404_and_an_unknown_action_is_400()
    {
        var client = factory.CreateClient();
        var created = await (await client.PostAsJsonAsync("/api/missions", ValidRequest()))
            .Content.ReadFromJsonAsync<Mission>(TestJson.Options);

        var unknown = await client.PostAsync($"/api/missions/{Guid.NewGuid()}/abort", content: null);
        var badAction = await client.PostAsJsonAsync($"/api/missions/{created!.Id}/abort", new AbortMissionRequest("explode"));

        Assert.Equal(HttpStatusCode.NotFound, unknown.StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, badAction.StatusCode);
    }

    [Fact]
    public async Task A_mission_outside_the_limits_is_rejected_with_every_reason()
    {
        var client = factory.CreateClient();
        var invalid = ValidRequest() with { Waypoints = [new WaypointDto(0, 0, 500), new WaypointDto(5000, 0, 5)] };

        var response = await client.PostAsJsonAsync("/api/missions", invalid);
        var body = await response.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("altitude", body);
        Assert.Contains("geofence", body);
    }
}
