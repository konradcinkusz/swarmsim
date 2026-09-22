using SwarmApi.Application.Contracts;
using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// The use-case orchestrator for missions (P9: endpoints delegate here; this validates,
/// builds the domain mission, dispatches through <see cref="ISwarmBridge"/>, and keeps
/// each mission's status). It holds no transport or bridge-specific concerns of its own.
/// </summary>
public sealed class MissionService(ISwarmBridge bridge, MissionLimits limits, TimeProvider time)
{
    private readonly MissionLog _log = new();

    public MissionService(ISwarmBridge bridge)
        : this(bridge, MissionLimits.Default, TimeProvider.System)
    {
    }

    public async Task<Mission> CreateMissionAsync(
        CreateMissionRequest request, CancellationToken cancellationToken = default)
    {
        MissionRequestValidator.Validate(request, limits);
        return await DispatchAsync(MissionFactory.Create(request, time.GetUtcNow()), cancellationToken);
    }

    /// <summary>Sends an already validated mission to the swarm and records it as the active one.</summary>
    public async Task<Mission> DispatchAsync(Mission mission, CancellationToken cancellationToken = default)
    {
        await bridge.DispatchMissionAsync(mission, cancellationToken);

        // A new mission replaces whatever the swarm was flying: the previous one did not
        // complete, and saying so is more honest than leaving it Active forever.
        foreach (var previous in _log.Active())
        {
            _log.TryEnd(previous.Id, MissionStatus.Aborted, time.GetUtcNow());
        }

        _log.Add(mission);
        return mission;
    }

    public async Task<SwarmState> GetSwarmStateAsync(CancellationToken cancellationToken = default)
    {
        var state = await bridge.GetStateAsync(cancellationToken);
        if (state is { ActiveMissionId: { } id, ActiveMissionComplete: true })
        {
            _log.TryEnd(id, MissionStatus.Completed, time.GetUtcNow());
        }

        return state;
    }

    public async Task<Mission?> GetMissionAsync(Guid missionId, CancellationToken cancellationToken = default)
    {
        var mission = _log.Get(missionId);
        if (mission is { Status: MissionStatus.Active })
        {
            // Refresh from the swarm so a mission that has finished reads as Completed
            // even when nobody has polled the state endpoint in between.
            await GetSwarmStateAsync(cancellationToken);
        }

        return mission;
    }

    /// <summary>
    /// Stops an active mission with the given override. Returns null for an unknown id and
    /// throws <see cref="MissionStateException"/> for one that is no longer active.
    /// </summary>
    public async Task<Mission?> AbortMissionAsync(
        Guid missionId, AbortMissionRequest? request, CancellationToken cancellationToken = default)
    {
        var command = MissionFactory.AbortCommand(request);
        var mission = await GetMissionAsync(missionId, cancellationToken);
        if (mission is null)
        {
            return null;
        }

        if (mission.Status != MissionStatus.Active)
        {
            throw new MissionStateException($"Mission {missionId} is {mission.Status}, not Active.");
        }

        await bridge.SendCommandAsync(command, missionId, cancellationToken);
        _log.TryEnd(missionId, MissionStatus.Aborted, time.GetUtcNow());
        return mission;
    }

    /// <summary>Lands every drone in place, whatever it is doing; any active mission ends as Aborted.</summary>
    public async Task LandAllAsync(CancellationToken cancellationToken = default)
    {
        await bridge.SendCommandAsync(SwarmCommand.Land, null, cancellationToken);
        foreach (var mission in _log.Active())
        {
            _log.TryEnd(mission.Id, MissionStatus.Aborted, time.GetUtcNow());
        }
    }
}
