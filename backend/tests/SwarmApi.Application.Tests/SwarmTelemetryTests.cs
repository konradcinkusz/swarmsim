using System.Collections.Concurrent;
using System.Diagnostics;
using System.Diagnostics.Metrics;
using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Application.Tests;

/// <summary>
/// The plan gate is visible in telemetry (P15), and every metric tag comes from a bounded
/// set — never an id (architecture-standards METRICS-EXPOSITION §1). Listeners are global,
/// so other tests' measurements may appear too; every assertion holds for them as well.
/// </summary>
public class SwarmTelemetryTests
{
    private static readonly HashSet<string> BoundedTags = ["type", "route", "outcome", "status", "decision", "reason"];

    [Fact]
    public async Task The_plan_gate_is_counted_and_traced_with_bounded_tags_only()
    {
        var measurements = new ConcurrentQueue<(string Instrument, Dictionary<string, object?> Tags)>();
        using var meters = new MeterListener();
        meters.InstrumentPublished = (instrument, listener) =>
        {
            if (instrument.Meter.Name == SwarmTelemetry.Name)
            {
                listener.EnableMeasurementEvents(instrument);
            }
        };
        meters.SetMeasurementEventCallback<long>((instrument, _, tags, _) =>
            measurements.Enqueue((instrument.Name, tags.ToArray().ToDictionary(t => t.Key, t => t.Value))));
        meters.Start();

        var spans = new ConcurrentQueue<string>();
        using var tracing = new ActivityListener
        {
            ShouldListenTo = source => source.Name == SwarmTelemetry.Name,
            Sample = (ref ActivityCreationOptions<ActivityContext> _) => ActivitySamplingResult.AllDataAndRecorded,
            ActivityStopped = activity => spans.Enqueue(activity.OperationName),
        };
        ActivitySource.AddActivityListener(tracing);

        var time = new FakeTimeProvider(new DateTimeOffset(2026, 9, 22, 12, 0, 0, TimeSpan.Zero));
        var bridge = new SimulatedSwarmBridge(time);
        var plans = new MissionPlanService(
            new MissionService(bridge, MissionLimits.Default, time), bridge, MissionLimits.Default, PlanningOptions.Default, time);
        var request = new CreateMissionRequest(
            "Telemetry", "waypoint", [new WaypointDto(0, 0, 5), new WaypointDto(20, 0, 5)], 2, 3.0, null);

        var plan = await plans.CreatePlanAsync(request, "agent");
        var approval = plans.Approve(plan.Id, "person")!;
        await Assert.ThrowsAsync<ApprovalRefusedException>(() => plans.DispatchAsync(plan.Id, "not-the-code"));
        await plans.DispatchAsync(plan.Id, approval.ApprovalCode);

        Assert.Contains(measurements, m => m.Instrument == "swarm.plans.proposed" && Equals(m.Tags["status"], "PendingApproval"));
        Assert.Contains(measurements, m => m.Instrument == "swarm.plans.decided" && Equals(m.Tags["decision"], "approved"));
        Assert.Contains(measurements, m => m.Instrument == "swarm.plans.dispatch_refused" && Equals(m.Tags["reason"], "code"));
        Assert.Contains(measurements, m => m.Instrument == "swarm.missions.dispatched" && Equals(m.Tags["route"], "plan"));
        Assert.All(measurements, m => Assert.Subset(BoundedTags, m.Tags.Keys.ToHashSet()));
        Assert.DoesNotContain(measurements, m => m.Tags.Values.Any(v => Guid.TryParse(v?.ToString(), out _)));
        Assert.Contains("plan.propose", spans);
        Assert.Contains("plan.dispatch", spans);
        Assert.Contains("mission.dispatch", spans);
    }
}
