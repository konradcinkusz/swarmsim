using System.Net.WebSockets;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using SwarmApi.Application;

namespace SwarmApi.Infrastructure;

public static class ServiceCollectionExtensions
{
    /// <summary>
    /// Registers <see cref="ISwarmBridge"/>: probes <c>RosBridge:Url</c> with a short
    /// timeout and registers <see cref="RosBridgeSwarmBridge"/> on success, or
    /// <see cref="SimulatedSwarmBridge"/> otherwise (P8). This is the one place that
    /// decision is made — see docs/adr/0003-rosbridge-degrade-pattern.md.
    /// </summary>
    public static async Task<IServiceCollection> AddSwarmBridgeAsync(
        this IServiceCollection services,
        IConfiguration configuration,
        ILogger logger,
        CancellationToken cancellationToken = default)
    {
        var options = configuration.GetSection(RosBridgeOptions.SectionName).Get<RosBridgeOptions>()
            ?? new RosBridgeOptions();

        if (!string.IsNullOrWhiteSpace(options.Url) && Uri.TryCreate(options.Url, UriKind.Absolute, out var uri))
        {
            var socket = new ClientWebSocket();
            using var timeoutCts = new CancellationTokenSource(TimeSpan.FromSeconds(options.ConnectTimeoutSeconds));
            using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);

            try
            {
                await socket.ConnectAsync(uri, linkedCts.Token);

                var bridge = new RosBridgeSwarmBridge(uri, socket);
                await bridge.StartAsync(cancellationToken);

                services.AddSingleton<ISwarmBridge>(bridge);
                logger.LogInformation("RosBridge reachable at {Url}; running in Connected mode.", uri);
                return services;
            }
            catch (Exception ex) when (ex is WebSocketException or OperationCanceledException)
            {
                socket.Dispose();
                logger.LogWarning(
                    ex, "RosBridge unreachable at {Url}; falling back to Simulated mode.", uri);
            }
        }
        else
        {
            logger.LogInformation("RosBridge:Url not configured; running in Simulated mode.");
        }

        services.AddSingleton<ISwarmBridge, SimulatedSwarmBridge>();
        return services;
    }
}
