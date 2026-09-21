using SwarmApi.Application.Contracts;
using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// The one seam between the API and the swarm (P10: interface + DI, no base class).
/// Two implementations exist: <c>RosBridgeSwarmBridge</c> (real, WebSocket to
/// rosbridge_suite) and <c>SimulatedSwarmBridge</c> (in-memory fallback). Which one is
/// registered is decided once, at startup, per the P8 degrade pattern documented in
/// docs/adr/0003-rosbridge-degrade-pattern.md — callers never branch on it.
/// </summary>
public interface ISwarmBridge
{
    SwarmBridgeMode Mode { get; }

    Task<Mission> DispatchMissionAsync(CreateMissionRequest request, CancellationToken cancellationToken = default);

    Task<SwarmState> GetStateAsync(CancellationToken cancellationToken = default);

    Task<Mission?> GetMissionAsync(Guid missionId, CancellationToken cancellationToken = default);
}
