using System.Net;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;

namespace SwarmApi.Api.Tests;

public class HealthEndpointTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    [Fact]
    public async Task Health_reports_ok_with_the_active_bridge_mode()
    {
        var client = factory.CreateClient();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();
        // RosBridge:Url is empty in appsettings.json (no test override), so this
        // process runs in Simulated mode (P8) — the same zero-dependency path
        // `git clone && dotnet run` gets.
        Assert.Contains("Simulated", body);
        // Same for Auth:Authority — Open mode (no token required anywhere) is what a
        // zero-config `dotnet run` gets; AuthEndpointTests covers the Enforced side.
        Assert.Contains("Open", body);
    }

    [Fact]
    public async Task Alive_reports_ok()
    {
        var client = factory.CreateClient();

        var response = await client.GetAsync("/alive");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}
