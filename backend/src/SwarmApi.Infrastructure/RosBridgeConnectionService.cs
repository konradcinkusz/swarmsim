using Microsoft.Extensions.Hosting;

namespace SwarmApi.Infrastructure;

/// <summary>
/// Runs <see cref="RosBridgeSwarmBridge.RunAsync"/> for the lifetime of the host, so the
/// connection is (re)established in the background and torn down on shutdown — the host
/// owns the lifecycle instead of <c>Program.cs</c> wiring disposal by hand.
/// </summary>
public sealed class RosBridgeConnectionService(RosBridgeSwarmBridge bridge) : BackgroundService
{
    protected override Task ExecuteAsync(CancellationToken stoppingToken) => bridge.RunAsync(stoppingToken);
}
