using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using SwarmApi.Application;
using Xunit;

namespace SwarmApi.Infrastructure.Tests;

/// <summary>
/// The one place the bridge is chosen (docs/adr/0003 and its amendments): configured means
/// real, unconfigured means simulated, and nothing in between.
/// </summary>
public class SwarmBridgeRegistrationTests
{
    [Fact]
    public async Task No_url_selects_the_simulated_swarm()
    {
        await using var provider = Build(url: null);

        Assert.IsType<SimulatedSwarmBridge>(provider.GetRequiredService<ISwarmBridge>());
        Assert.Empty(provider.GetServices<IHostedService>());
    }

    [Theory]
    [InlineData("ws://sim:9090")]
    [InlineData("wss://swarm.example.org/rosbridge")]
    public async Task A_websocket_url_selects_the_real_bridge_and_its_connection_service(string url)
    {
        // The real bridge is IAsyncDisposable only, so the container must be disposed async.
        await using var provider = Build(url);

        Assert.IsType<RosBridgeSwarmBridge>(provider.GetRequiredService<ISwarmBridge>());
        Assert.Contains(provider.GetServices<IHostedService>(), s => s is RosBridgeConnectionService);
    }

    [Theory]
    [InlineData("http://sim:9090")]
    [InlineData("sim:9090")]
    [InlineData("not a url")]
    public void A_configured_url_that_is_not_a_websocket_stops_startup(string url)
    {
        // Before, this fell back to the simulated swarm with a warning in the log — stand-in
        // drones in front of an operator who configured real ones.
        var error = Assert.Throws<InvalidOperationException>(() => Build(url));

        Assert.Contains(url, error.Message, StringComparison.Ordinal);
    }

    private static ServiceProvider Build(string? url)
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["RosBridge:Url"] = url })
            .Build();
        var services = new ServiceCollection();
        services.AddSingleton(typeof(ILogger<>), typeof(NullLogger<>));
        services.AddSwarmBridge(configuration, NullLogger.Instance);
        return services.BuildServiceProvider();
    }
}
