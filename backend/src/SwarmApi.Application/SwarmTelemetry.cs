using System.Diagnostics;
using System.Diagnostics.Metrics;
using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// The API's own spans and metrics (P15), in the BCL's <see cref="ActivitySource"/> and
/// <see cref="Meter"/> so this layer needs no package; SwarmApi.ServiceDefaults exports
/// them over OTLP when an endpoint is configured, and nothing leaves the process when not.
/// Every tag comes from a bounded set — mission type, outcome, plan status, refusal
/// reason — and never from an id (architecture-standards METRICS-EXPOSITION §1).
/// </summary>
public static class SwarmTelemetry
{
    public const string Name = "SwarmApi";

    public static readonly ActivitySource Source = new(Name);

    private static readonly Meter Meter = new(Name);

    private static readonly Counter<long> MissionsDispatched = Meter.CreateCounter<long>(
        "swarm.missions.dispatched", unit: "{mission}", description: "Missions sent to the swarm.");

    private static readonly Counter<long> MissionsEnded = Meter.CreateCounter<long>(
        "swarm.missions.ended", unit: "{mission}", description: "Missions that stopped being active, by outcome.");

    private static readonly Counter<long> PlansProposed = Meter.CreateCounter<long>(
        "swarm.plans.proposed", unit: "{plan}", description: "Mission plans proposed, by the status their preview gave them.");

    private static readonly Counter<long> PlanDecisions = Meter.CreateCounter<long>(
        "swarm.plans.decided", unit: "{plan}", description: "Mission plans approved or rejected by a person.");

    private static readonly Counter<long> DispatchRefusals = Meter.CreateCounter<long>(
        "swarm.plans.dispatch_refused", unit: "{request}", description: "Plan dispatches refused, by reason.");

    /// <param name="route"><c>direct</c> (POST /api/missions) or <c>plan</c> (an approved plan).</param>
    public static void MissionDispatched(Mission mission, string route) =>
        MissionsDispatched.Add(1, new("type", mission.Type.ToString()), new("route", route));

    public static void MissionEnded(MissionStatus outcome) =>
        MissionsEnded.Add(1, new KeyValuePair<string, object?>("outcome", outcome.ToString()));

    public static void PlanProposed(MissionPlanStatus status) =>
        PlansProposed.Add(1, new KeyValuePair<string, object?>("status", status.ToString()));

    /// <param name="decision"><c>approved</c> or <c>rejected</c>.</param>
    public static void PlanDecided(string decision) =>
        PlanDecisions.Add(1, new KeyValuePair<string, object?>("decision", decision));

    /// <param name="reason"><c>code</c> (wrong approval code) or <c>state</c> (not approved, used, expired).</param>
    public static void DispatchRefused(string reason) =>
        DispatchRefusals.Add(1, new KeyValuePair<string, object?>("reason", reason));
}
