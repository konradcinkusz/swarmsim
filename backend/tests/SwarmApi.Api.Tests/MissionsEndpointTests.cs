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
}
