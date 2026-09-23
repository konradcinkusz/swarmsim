using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// The plans this process holds. In memory, like <see cref="MissionLog"/> (DEVIATIONS.md,
/// P3/P4 row), and bounded: the oldest plans that are no longer waiting on anyone are
/// forgotten first.
/// </summary>
public sealed class MissionPlanStore(int capacity = 500)
{
    private readonly object _lock = new();
    private readonly Dictionary<Guid, MissionPlan> _plans = new();
    private readonly LinkedList<Guid> _order = new();

    /// <summary>Every mutation of a plan happens under this lock, so a check-then-act is atomic.</summary>
    public T Update<T>(Guid id, Func<MissionPlan?, T> change)
    {
        lock (_lock)
        {
            return change(_plans.GetValueOrDefault(id));
        }
    }

    public void Add(MissionPlan plan)
    {
        lock (_lock)
        {
            _plans[plan.Id] = plan;
            _order.AddLast(plan.Id);
            var node = _order.First;
            while (_plans.Count > capacity && node is not null)
            {
                var next = node.Next;
                if (_plans[node.Value].Status is not (MissionPlanStatus.PendingApproval or MissionPlanStatus.Approved))
                {
                    _plans.Remove(node.Value);
                    _order.Remove(node);
                }

                node = next;
            }
        }
    }

    public IReadOnlyList<MissionPlan> Recent(int limit)
    {
        lock (_lock)
        {
            return _order.Reverse().Take(limit).Select(id => _plans[id]).ToList();
        }
    }
}
