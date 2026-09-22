using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using SwarmApi.Application.Contracts;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>
/// Enforced-mode behaviour through the real host, not just the DI registration
/// (<see cref="AuthenticationRegistrationTests"/> covers that half). The authority is
/// supplied with <c>UseSetting</c>, which — unlike <c>ConfigureAppConfiguration</c> —
/// reaches the configuration <c>Program.cs</c> reads before <c>builder.Build()</c>, so the
/// endpoint gating decided there is the one under test. No token is ever minted: every
/// assertion here is about what an unauthenticated caller can and cannot reach, which is
/// the bespoke part (see docs/adr/0005-mcp-server-and-bearer-auth.md).
/// </summary>
public class EnforcedAuthEndpointTests
{
    private static CreateMissionRequest ValidRequest() => new(
        Name: "Enforced-mode probe",
        Type: "waypoint",
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(10, 0, 5)],
        DroneCount: 2,
        SpacingMeters: 2.0);

    private static WebApplicationFactory<Program> Factory(string authority, bool? requireHttpsMetadata = null) =>
        new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
        {
            builder.UseSetting("Auth:Authority", authority);
            if (requireHttpsMetadata is not null)
            {
                builder.UseSetting("Auth:RequireHttpsMetadata", requireHttpsMetadata.Value.ToString());
            }
        });

    [Fact]
    public async Task Creating_a_mission_without_a_token_is_rejected_with_401()
    {
        using var factory = Factory("https://authservice.invalid");
        var client = factory.CreateClient();

        var response = await client.PostAsJsonAsync("/api/missions", ValidRequest());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Reads_and_health_stay_open_and_health_reports_enforced()
    {
        using var factory = Factory("https://authservice.invalid");
        var client = factory.CreateClient();

        var state = await client.GetAsync("/api/swarm/state");
        var health = await client.GetStringAsync("/health");

        Assert.Equal(HttpStatusCode.OK, state.StatusCode);
        Assert.Contains("Enforced", health);
    }

    [Fact]
    public async Task An_http_authority_with_https_metadata_disabled_still_answers_401_not_500()
    {
        // The compose `auth` profile's shape: authservice over plain http inside the
        // network. Without Auth:RequireHttpsMetadata=false, JwtBearer rejects the http
        // metadata address while building its options, so this request used to be a 500.
        using var factory = Factory("http://authservice:8080", requireHttpsMetadata: false);
        var client = factory.CreateClient();

        var response = await client.PostAsJsonAsync("/api/missions", ValidRequest());

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }
}
