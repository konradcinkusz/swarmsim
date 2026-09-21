using SwarmApi.Application.Contracts;
using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// The one use-case orchestrator for this service (P9: endpoints delegate here, this
/// validates and delegates to <see cref="ISwarmBridge"/>; it holds no transport or
/// bridge-specific concerns of its own).
/// </summary>
public sealed class MissionService(ISwarmBridge bridge)
{
    public async Task<Mission> CreateMissionAsync(
        CreateMissionRequest request, CancellationToken cancellationToken = default)
    {
        MissionRequestValidator.Validate(request);
        return await bridge.DispatchMissionAsync(request, cancellationToken);
    }

    public Task<SwarmState> GetSwarmStateAsync(CancellationToken cancellationToken = default) =>
        bridge.GetStateAsync(cancellationToken);

    public Task<Mission?> GetMissionAsync(Guid missionId, CancellationToken cancellationToken = default) =>
        bridge.GetMissionAsync(missionId, cancellationToken);
}
