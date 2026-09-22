using SwarmApi.Application.Contracts;
using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// The write gate between an agent and the swarm (docs/adr/0009): a mission is proposed as a
/// plan, checked for conflicts, approved by a person, and dispatched only with the
/// single-use code that approval produced. The service enforces every step itself — an
/// agent's good behaviour is not part of the gate.
/// </summary>
public sealed class MissionPlanService(
    MissionService missions, ISwarmBridge bridge, MissionLimits limits, PlanningOptions options, TimeProvider time)
{
    private readonly MissionPlanStore _store = new();

    /// <summary>Validates and previews a mission; the plan is Conflicted if its paths bring drones too close.</summary>
    public async Task<MissionPlanView> CreatePlanAsync(
        CreateMissionRequest request, string? proposedBy, CancellationToken cancellationToken = default)
    {
        MissionRequestValidator.Validate(request, limits);
        var now = time.GetUtcNow();
        var mission = MissionFactory.Create(request, now);
        var state = await bridge.GetStateAsync(cancellationToken);
        var preview = MissionPlanner.Preview(mission, state.Drones.ToDictionary(d => d.Id, d => d.Position), options);

        var plan = new MissionPlan
        {
            Id = Guid.NewGuid(),
            Mission = mission,
            Preview = preview,
            CreatedAtUtc = now,
            CreatedBy = proposedBy,
            DecideByUtc = now.AddMinutes(options.DecisionWindowMinutes),
            Status = preview.Conflicts.Count > 0 ? MissionPlanStatus.Conflicted : MissionPlanStatus.PendingApproval,
        };
        _store.Add(plan);
        return MissionPlanView.From(plan);
    }

    public MissionPlanView? GetPlan(Guid planId) =>
        _store.Update(planId, plan => plan is null ? null : MissionPlanView.From(Expire(plan)));

    public IReadOnlyList<MissionPlanView> RecentPlans(int limit)
    {
        var plans = _store.Recent(Math.Clamp(limit, 1, 100));
        return plans.Select(p => _store.Update(p.Id, plan => MissionPlanView.From(Expire(plan!)))).ToList();
    }

    /// <summary>
    /// Approves a pending plan and returns its approval code — the only time the code is
    /// ever shown. Refused (409) for a plan in any other state, a conflicted one included,
    /// and (403) for the identity that proposed it, when both are known.
    /// </summary>
    public PlanApproval? Approve(Guid planId, string? approvedBy) => _store.Update(planId, plan =>
    {
        if (plan is null)
        {
            return null;
        }

        Expire(plan);
        if (plan.Status == MissionPlanStatus.Conflicted)
        {
            throw new PlanStateException(
                $"Plan {planId} has {plan.Preview.Conflicts.Count} conflict(s) and cannot be approved; propose a new plan.");
        }

        if (plan.Status != MissionPlanStatus.PendingApproval)
        {
            throw new PlanStateException($"Plan {planId} is {plan.Status}, not PendingApproval.");
        }

        if (approvedBy is not null && approvedBy == plan.CreatedBy)
        {
            throw new ApprovalRefusedException("A plan cannot be approved by the identity that proposed it.");
        }

        var code = ApprovalCode.New();
        var now = time.GetUtcNow();
        plan.ApprovalCodeHash = ApprovalCode.Hash(code);
        plan.Status = MissionPlanStatus.Approved;
        plan.DecidedAtUtc = now;
        plan.DecidedBy = approvedBy;
        plan.ApprovalExpiresAtUtc = now.AddMinutes(options.ApprovalValidityMinutes);
        return new PlanApproval(MissionPlanView.From(plan), code, plan.ApprovalExpiresAtUtc.Value);
    });

    public MissionPlanView? Reject(Guid planId, string? rejectedBy) => _store.Update(planId, plan =>
    {
        if (plan is null)
        {
            return null;
        }

        Expire(plan);
        if (plan.Status is not (MissionPlanStatus.PendingApproval or MissionPlanStatus.Conflicted or MissionPlanStatus.Approved))
        {
            throw new PlanStateException($"Plan {planId} is {plan.Status} and can no longer be rejected.");
        }

        plan.Status = MissionPlanStatus.Rejected;
        plan.ApprovalCodeHash = null;
        plan.DecidedAtUtc = time.GetUtcNow();
        plan.DecidedBy = rejectedBy;
        return MissionPlanView.From(plan);
    });

    /// <summary>
    /// Dispatches an approved plan's mission with its approval code, once. The code is
    /// consumed before the mission is sent, so two callers racing with the same code cannot
    /// both dispatch; if the swarm is unreachable the code is given back, so the same
    /// approval can be retried.
    /// </summary>
    public async Task<Mission?> DispatchAsync(Guid planId, string? approvalCode, CancellationToken cancellationToken = default)
    {
        var claimed = _store.Update<(MissionPlan Plan, byte[] Hash)?>(planId, plan =>
        {
            if (plan is null)
            {
                return null;
            }

            Expire(plan);
            if (plan.Status == MissionPlanStatus.Dispatched)
            {
                throw new PlanStateException($"Plan {planId} was already dispatched as mission {plan.MissionId}.");
            }

            if (plan.Status != MissionPlanStatus.Approved)
            {
                throw new PlanStateException($"Plan {planId} is {plan.Status}; only an approved plan can be dispatched.");
            }

            if (!ApprovalCode.Matches(approvalCode, plan.ApprovalCodeHash))
            {
                throw new ApprovalRefusedException("The approval code does not match this plan's approval.");
            }

            var consumed = plan.ApprovalCodeHash!;
            plan.ApprovalCodeHash = null;
            return (plan, consumed);
        });

        if (claimed is not { } claim)
        {
            return null;
        }

        try
        {
            var mission = await missions.DispatchAsync(MissionFactory.Launch(claim.Plan.Mission, time.GetUtcNow()), cancellationToken);
            _store.Update(planId, plan =>
            {
                plan!.Status = MissionPlanStatus.Dispatched;
                plan.MissionId = mission.Id;
                return plan;
            });
            return mission;
        }
        catch (SwarmUnavailableException)
        {
            _store.Update(planId, plan => plan!.ApprovalCodeHash = claim.Hash);
            throw;
        }
    }

    private MissionPlan Expire(MissionPlan plan)
    {
        var now = time.GetUtcNow();
        var lapsed = plan.Status switch
        {
            MissionPlanStatus.PendingApproval or MissionPlanStatus.Conflicted => now > plan.DecideByUtc,
            MissionPlanStatus.Approved => now > plan.ApprovalExpiresAtUtc,
            _ => false,
        };
        if (lapsed)
        {
            plan.Status = MissionPlanStatus.Expired;
            plan.ApprovalCodeHash = null;
        }

        return plan;
    }
}
