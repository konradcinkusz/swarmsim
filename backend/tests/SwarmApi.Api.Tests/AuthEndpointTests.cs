using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using SwarmApi.Application.Contracts;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>
/// Covers the Enforced side of the Open/Enforced degrade pattern (P8) — see
/// docs/adr/0005-mcp-server-and-bearer-auth.md. The Open-mode (default) behavior is
/// exercised by every other test in this project, which all run unauthenticated against
/// the default factory; this class only overrides <c>Auth:Authority</c> to flip the
/// switch. A missing `Authorization` header is rejected by the JWT bearer handler before
/// it ever needs to fetch JWKS metadata, so none of this needs network access.
/// </summary>
public class AuthEndpointTests
{
    private static WebApplicationFactory<Program> EnforcedFactory() =>
        new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
            builder.ConfigureAppConfiguration((_, config) =>
                config.AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["Auth:Authority"] = "https://authservice.invalid",
                })));

    private static CreateMissionRequest ValidRequest() => new(
        Name: "Auth test sweep",
        Type: "waypoint",
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(10, 0, 5)],
        DroneCount: 1,
        SpacingMeters: 2.0);

    [Fact]
    public async Task Post_missions_without_a_token_returns_401_when_auth_is_enforced()
    {
        using var factory = EnforcedFactory();
        var client = factory.CreateClient();

        var response = await client.PostAsJsonAsync("/api/missions", ValidRequest());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Health_reports_enforced_when_auth_authority_is_configured()
    {
        using var factory = EnforcedFactory();
        var client = factory.CreateClient();

        var response = await client.GetAsync("/health");

        var body = await response.Content.ReadAsStringAsync();
        Assert.Contains("Enforced", body);
    }

    [Fact]
    public async Task Get_swarm_state_stays_open_even_when_auth_is_enforced()
    {
        using var factory = EnforcedFactory();
        var client = factory.CreateClient();

        var response = await client.GetAsync("/api/swarm/state");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}
