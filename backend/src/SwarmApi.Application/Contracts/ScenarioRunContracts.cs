using System.Text.Json.Serialization;

namespace SwarmApi.Application.Contracts;

/// <summary>
/// A scenario suite report as the scenario runner writes it — the wire shape of
/// contracts/scenario/report.v1.schema.json, snake_case as the runner emits it. Kept whole:
/// a stored run is the report, not a digest of it.
/// </summary>
public sealed record ScenarioReport(
    [property: JsonPropertyName("version")] int Version,
    [property: JsonPropertyName("sut")] string Sut,
    [property: JsonPropertyName("seeds")] IReadOnlyList<int> Seeds,
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("counts")] ScenarioCounts Counts,
    [property: JsonPropertyName("errors")] IReadOnlyList<string> Errors,
    [property: JsonPropertyName("scenarios")] IReadOnlyList<ScenarioResult> Scenarios,
    [property: JsonPropertyName("mutation")] MutationResult? Mutation);

public sealed record ScenarioCounts(
    [property: JsonPropertyName("passed")] int Passed,
    [property: JsonPropertyName("failed")] int Failed,
    [property: JsonPropertyName("xfail")] int Xfail,
    [property: JsonPropertyName("xpass")] int Xpass);

public sealed record ScenarioResult(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("source")] string? Source,
    [property: JsonPropertyName("description")] string Description,
    [property: JsonPropertyName("expect")] string Expect,
    [property: JsonPropertyName("expect_reason")] string? ExpectReason,
    [property: JsonPropertyName("outcome")] string Outcome,
    [property: JsonPropertyName("killed_mutants")] IReadOnlyList<string>? KilledMutants,
    [property: JsonPropertyName("runs")] IReadOnlyList<ScenarioSeedRun> Runs);

public sealed record ScenarioSeedRun(
    [property: JsonPropertyName("seed")] int Seed,
    [property: JsonPropertyName("passed")] bool Passed,
    [property: JsonPropertyName("wall_time_s")] double WallTimeSeconds,
    [property: JsonPropertyName("assertions")] IReadOnlyList<AssertionResult> Assertions);

public sealed record AssertionResult(
    [property: JsonPropertyName("assertion")] string Assertion,
    [property: JsonPropertyName("passed")] bool Passed,
    [property: JsonPropertyName("measured")] double? Measured,
    [property: JsonPropertyName("unit")] string? Unit,
    [property: JsonPropertyName("violations")] IReadOnlyList<AssertionViolation> Violations);

public sealed record AssertionViolation(
    [property: JsonPropertyName("drones")] IReadOnlyList<string> Drones,
    [property: JsonPropertyName("t_s")] double? AtSeconds,
    [property: JsonPropertyName("measured")] double? Measured,
    [property: JsonPropertyName("threshold")] double? Threshold,
    [property: JsonPropertyName("description")] string Description);

public sealed record MutationResult(
    [property: JsonPropertyName("mutants")] IReadOnlyList<MutantInfo> Mutants,
    [property: JsonPropertyName("survivors")] IReadOnlyList<string> Survivors,
    [property: JsonPropertyName("toothless_scenarios")] IReadOnlyList<string> ToothlessScenarios);

public sealed record MutantInfo(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("breaks")] string Breaks);

/// <summary>The <c>POST /api/scenario-runs</c> body: a report, and a label saying what was tested (a commit, a branch, a build).</summary>
public sealed record IngestScenarioRunRequest(string? Label, ScenarioReport? Report);

/// <summary>A stored run.</summary>
public sealed record ScenarioRun(
    Guid Id, DateTimeOffset ReceivedAtUtc, string? Label, string? SubmittedBy, ScenarioReport Report)
{
    public ScenarioRunSummary Summary() => new(
        Id,
        ReceivedAtUtc,
        Label,
        SubmittedBy,
        Report.Sut,
        Report.Ok,
        Report.Counts,
        Report.Scenarios.Count,
        Report.Seeds.Count,
        Report.Mutation?.Survivors ?? []);
}

/// <summary>A run as a list shows it: what was tested, and how it went.</summary>
public sealed record ScenarioRunSummary(
    Guid Id,
    DateTimeOffset ReceivedAtUtc,
    string? Label,
    string? SubmittedBy,
    string Sut,
    bool Ok,
    ScenarioCounts Counts,
    int ScenarioCount,
    int SeedCount,
    IReadOnlyList<string> SurvivingMutants);

/// <summary>What changed between two runs, scenario by scenario.</summary>
public sealed record ScenarioRunComparison(
    ScenarioRunSummary Base,
    ScenarioRunSummary Head,
    IReadOnlyList<ScenarioChange> Scenarios,
    IReadOnlyList<string> NewSurvivors,
    IReadOnlyList<string> NoLongerSurviving);

/// <summary>
/// One scenario across two runs. <see cref="Change"/>: <c>regressed</c> (met its expectation
/// in the base run, not in the head), <c>fixed</c> (the reverse), <c>unchanged</c>,
/// <c>changed</c> (a different outcome that meets the expectation either way — the
/// expectation itself changed), <c>added</c> or <c>removed</c>.
/// </summary>
public sealed record ScenarioChange(
    string Name,
    string? BaseOutcome,
    string? HeadOutcome,
    string Change,
    IReadOnlyList<MeasurementChange> Measurements);

/// <summary>An assertion's measured value, averaged over the run's seeds, in both runs.</summary>
public sealed record MeasurementChange(
    string Assertion, string? Unit, double? BaseMean, double? HeadMean, double? Delta);

/// <summary>An ingested run that cannot be stored as it is; mapped to 400 with every reason.</summary>
public sealed class ScenarioRunValidationException(IReadOnlyList<string> errors)
    : Exception(string.Join(" ", errors))
{
    public IReadOnlyList<string> Errors { get; } = errors;
}
