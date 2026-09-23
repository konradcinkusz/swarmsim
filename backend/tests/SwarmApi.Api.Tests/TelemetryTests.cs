using System.Text.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using SwarmApi.ServiceDefaults;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>P15 with P8's degrade shape: OTLP export when an endpoint is configured, "Off" otherwise, and /health says which.</summary>
public class TelemetryTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private static async Task<string?> TelemetryMode(HttpClient client)
    {
        using var health = JsonDocument.Parse(await client.GetStringAsync("/health"));
        return health.RootElement.GetProperty("checks").GetProperty(Telemetry.HealthCheckName)
            .GetProperty("data").GetProperty("telemetry").GetString();
    }

    [Fact]
    public async Task With_no_endpoint_nothing_is_exported_and_health_says_Off()
    {
        Assert.Equal("Off", await TelemetryMode(factory.CreateClient()));
    }

    [Fact]
    public async Task With_an_endpoint_health_says_Otlp()
    {
        // Nothing listens there: exporting fails in the background, and the service is unaffected.
        await using var otlp = factory.WithWebHostBuilder(host =>
            host.UseSetting(Telemetry.EndpointVariable, "http://127.0.0.1:1"));

        var client = otlp.CreateClient();

        Assert.Equal("Otlp", await TelemetryMode(client));
        Assert.Equal(System.Net.HttpStatusCode.OK, (await client.GetAsync("/api/swarm/state")).StatusCode);
    }
}
