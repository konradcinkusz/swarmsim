using SwarmApi.Application.Contracts;

namespace SwarmApi.Application;

/// <summary>
/// Where scenario runs are kept (docs/adr/0011). Two implementations: in memory, the
/// default, forgotten on restart, and one JSON file per run in a directory, for a
/// deployment with a volume. <see cref="Mode"/> is what <c>/health</c> reports.
/// </summary>
public interface IScenarioRunStore
{
    string Mode { get; }

    int Count { get; }

    Task AddAsync(ScenarioRun run, CancellationToken cancellationToken = default);

    Task<ScenarioRun?> GetAsync(Guid id, CancellationToken cancellationToken = default);

    /// <summary>The most recent runs first, at most <paramref name="limit"/>.</summary>
    Task<IReadOnlyList<ScenarioRunSummary>> RecentAsync(int limit, CancellationToken cancellationToken = default);
}

/// <summary>
/// Stores the reports the scenario runner produces and compares two of them — the hosted
/// half of the scenario instrument (ADR-0008 runs the scenarios in the caller's CI; this
/// remembers what they said). Nothing here runs a scenario.
/// </summary>
public sealed class ScenarioRunService(IScenarioRunStore store, TimeProvider time)
{
    public const int MaxLabelLength = 200;
    public const int MaxScenarios = 1000;
    public const int MaxSeeds = 1000;

    public async Task<ScenarioRunSummary> IngestAsync(
        IngestScenarioRunRequest request, string? submittedBy, CancellationToken cancellationToken = default)
    {
        var report = Validate(request);
        var run = new ScenarioRun(Guid.NewGuid(), time.GetUtcNow(), request.Label?.Trim(), submittedBy, report);
        await store.AddAsync(run, cancellationToken);
        return run.Summary();
    }

    public Task<ScenarioRun?> GetAsync(Guid id, CancellationToken cancellationToken = default) =>
        store.GetAsync(id, cancellationToken);

    public Task<IReadOnlyList<ScenarioRunSummary>> RecentAsync(int limit, CancellationToken cancellationToken = default) =>
        store.RecentAsync(Math.Clamp(limit, 1, 100), cancellationToken);

    /// <summary>Null when either run is unknown.</summary>
    public async Task<ScenarioRunComparison?> CompareAsync(
        Guid baseId, Guid headId, CancellationToken cancellationToken = default)
    {
        var baseRun = await store.GetAsync(baseId, cancellationToken);
        var headRun = await store.GetAsync(headId, cancellationToken);
        return baseRun is null || headRun is null ? null : Compare(baseRun, headRun);
    }

    public static ScenarioRunComparison Compare(ScenarioRun baseRun, ScenarioRun headRun)
    {
        var before = baseRun.Report.Scenarios.ToDictionary(s => s.Name);
        var after = headRun.Report.Scenarios.ToDictionary(s => s.Name);
        var names = baseRun.Report.Scenarios.Select(s => s.Name)
            .Concat(headRun.Report.Scenarios.Select(s => s.Name).Where(n => !before.ContainsKey(n)));

        var changes = names.Select(name =>
        {
            before.TryGetValue(name, out var b);
            after.TryGetValue(name, out var h);
            return new ScenarioChange(name, b?.Outcome, h?.Outcome, ChangeOf(b, h), Measurements(b, h));
        }).ToList();

        var baseSurvivors = baseRun.Report.Mutation?.Survivors ?? [];
        var headSurvivors = headRun.Report.Mutation?.Survivors ?? [];
        return new ScenarioRunComparison(
            baseRun.Summary(),
            headRun.Summary(),
            changes,
            headSurvivors.Except(baseSurvivors).ToList(),
            baseSurvivors.Except(headSurvivors).ToList());
    }

    private static bool MetExpectation(ScenarioResult scenario) => scenario.Outcome is "passed" or "xfail";

    private static string ChangeOf(ScenarioResult? before, ScenarioResult? after) => (before, after) switch
    {
        (null, _) => "added",
        (_, null) => "removed",
        _ when MetExpectation(before) && !MetExpectation(after) => "regressed",
        _ when !MetExpectation(before) && MetExpectation(after) => "fixed",
        _ when before.Outcome != after.Outcome => "changed",
        _ => "unchanged",
    };

    /// <summary>
    /// Every assertion's measured value averaged over the seeds, matched between the runs by
    /// its name and its occurrence (a scenario may assert the same thing twice).
    /// </summary>
    private static IReadOnlyList<MeasurementChange> Measurements(ScenarioResult? before, ScenarioResult? after)
    {
        var b = Means(before);
        var h = Means(after);
        return b.Keys.Concat(h.Keys.Where(k => !b.ContainsKey(k)))
            .Select(key =>
            {
                b.TryGetValue(key, out var bm);
                h.TryGetValue(key, out var hm);
                var delta = bm.Mean is { } x && hm.Mean is { } y ? Math.Round(y - x, 4) : (double?)null;
                return new MeasurementChange(key.Label, bm.Unit ?? hm.Unit, bm.Mean, hm.Mean, delta);
            })
            .ToList();
    }

    private static Dictionary<(string Label, int Occurrence), (string? Unit, double? Mean)> Means(ScenarioResult? scenario)
    {
        var values = new Dictionary<(string, int), (string? Unit, List<double> Values)>();
        foreach (var run in scenario?.Runs ?? [])
        {
            var seen = new Dictionary<string, int>();
            foreach (var assertion in run.Assertions)
            {
                var occurrence = seen[assertion.Assertion] = seen.GetValueOrDefault(assertion.Assertion) + 1;
                var label = occurrence == 1 ? assertion.Assertion : $"{assertion.Assertion} #{occurrence}";
                if (!values.TryGetValue((label, occurrence), out var entry))
                {
                    entry = (assertion.Unit, []);
                    values[(label, occurrence)] = entry;
                }

                if (assertion.Measured is { } measured && double.IsFinite(measured))
                {
                    entry.Values.Add(measured);
                }
            }
        }

        return values.ToDictionary(
            kv => kv.Key,
            kv => (kv.Value.Unit, kv.Value.Values.Count > 0 ? Math.Round(kv.Value.Values.Average(), 4) : (double?)null));
    }

    private static ScenarioReport Validate(IngestScenarioRunRequest request)
    {
        var errors = new List<string>();
        if (request.Label is { Length: > MaxLabelLength })
        {
            errors.Add($"label: at most {MaxLabelLength} characters.");
        }

        var report = request.Report;
        if (report is null)
        {
            errors.Add("report: required — the JSON `python -m swarm_coordination.scenarios run --json` writes.");
            throw new ScenarioRunValidationException(errors);
        }

        if (report.Version != 1)
        {
            errors.Add($"report.version: {report.Version} is not a version this API reads (1).");
        }

        if (string.IsNullOrWhiteSpace(report.Sut))
        {
            errors.Add("report.sut: required.");
        }

        if (report.Seeds is null || report.Seeds.Count is 0 or > MaxSeeds)
        {
            errors.Add($"report.seeds: between 1 and {MaxSeeds}.");
        }

        if (report.Scenarios is null || report.Scenarios.Count > MaxScenarios)
        {
            errors.Add($"report.scenarios: at most {MaxScenarios}.");
        }
        else
        {
            var duplicates = report.Scenarios.GroupBy(s => s.Name).Where(g => g.Count() > 1).Select(g => g.Key).ToList();
            if (duplicates.Count > 0)
            {
                errors.Add($"report.scenarios: names must be unique; repeated: {string.Join(", ", duplicates)}.");
            }

            if (report.Scenarios.Any(s => s.Outcome is not ("passed" or "failed" or "xfail" or "xpass")))
            {
                errors.Add("report.scenarios[].outcome: one of passed, failed, xfail, xpass.");
            }
        }

        if (report.Counts is null)
        {
            errors.Add("report.counts: required.");
        }

        if (errors.Count > 0)
        {
            throw new ScenarioRunValidationException(errors);
        }

        return report;
    }
}
