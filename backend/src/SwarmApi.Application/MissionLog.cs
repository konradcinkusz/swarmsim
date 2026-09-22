using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// The missions this process has dispatched, and their status. In memory by design for
/// now (docs/architecture/DEVIATIONS.md, P3/P4 row): bounded, so a long-running process
/// cannot grow it without limit — the oldest finished missions are forgotten first, and an
/// active one never is.
/// </summary>
public sealed class MissionLog(int capacity = 1000)
{
    private readonly object _lock = new();
    private readonly Dictionary<Guid, Mission> _missions = new();
    private readonly LinkedList<Guid> _order = new();

    public void Add(Mission mission)
    {
        lock (_lock)
        {
            _missions[mission.Id] = mission;
            _order.AddLast(mission.Id);
            Trim();
        }
    }

    public Mission? Get(Guid id)
    {
        lock (_lock)
        {
            return _missions.GetValueOrDefault(id);
        }
    }

    /// <summary>Every mission still flying — normally at most one, since a new dispatch replaces the swarm's task.</summary>
    public IReadOnlyList<Mission> Active()
    {
        lock (_lock)
        {
            return _missions.Values.Where(m => m.Status == MissionStatus.Active).ToList();
        }
    }

    /// <summary>Moves an active mission to a terminal status; returns false if it was not active.</summary>
    public bool TryEnd(Guid id, MissionStatus status, DateTimeOffset now)
    {
        lock (_lock)
        {
            if (!_missions.TryGetValue(id, out var mission) || mission.Status != MissionStatus.Active)
            {
                return false;
            }

            mission.Status = status;
            mission.EndedAtUtc = now;
            return true;
        }
    }

    private void Trim()
    {
        var node = _order.First;
        while (_missions.Count > capacity && node is not null)
        {
            var next = node.Next;
            if (_missions[node.Value].Status != MissionStatus.Active)
            {
                _missions.Remove(node.Value);
                _order.Remove(node);
            }

            node = next;
        }
    }
}
