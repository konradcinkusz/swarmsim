using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// The one seam between the API and the swarm (P10: interface + DI, no base class).
/// Two implementations exist: <c>RosBridgeSwarmBridge</c> (real, WebSocket to
/// rosbridge_suite) and <c>SimulatedSwarmBridge</c> (in-memory stand-in). Which one is
/// registered is decided once, by configuration alone (docs/adr/0003 and its 2026-09-22
/// amendments); whether the real one is currently connected is <see cref="Mode"/>, live.
/// </summary>
public interface ISwarmBridge
{
    /// <summary>The bridge's live mode: Connected or Disconnected for the real bridge, Simulated for the stand-in.</summary>
    SwarmBridgeMode Mode { get; }

    /// <summary>When swarm state last arrived from the swarm; null if it never has (or, for the simulated bridge, not applicable).</summary>
    DateTimeOffset? LastStateReceivedUtc { get; }

    /// <summary>Hands a validated mission to the swarm. Throws <c>SwarmUnavailableException</c> when it cannot.</summary>
    Task DispatchMissionAsync(Mission mission, CancellationToken cancellationToken = default);

    /// <summary>Sends a swarm-wide override (<see cref="SwarmCommand"/>). Throws <c>SwarmUnavailableException</c> when it cannot.</summary>
    Task SendCommandAsync(SwarmCommand command, Guid? missionId, CancellationToken cancellationToken = default);

    Task<SwarmState> GetStateAsync(CancellationToken cancellationToken = default);
}
