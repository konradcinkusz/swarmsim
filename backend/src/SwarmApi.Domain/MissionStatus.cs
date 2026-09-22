namespace SwarmApi.Domain;

/// <summary>A mission's lifecycle: dispatched missions are Active until the swarm reports them done or an operator aborts them.</summary>
public enum MissionStatus
{
    Active,
    Completed,
    Aborted,
}
