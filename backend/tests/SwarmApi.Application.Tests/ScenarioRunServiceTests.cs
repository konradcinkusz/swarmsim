using System.Text.Json;
using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Application.Tests;

/// <summary>Ingesting, validating and comparing scenario runs (docs/adr/0011), on the report contract's own example.</summary>
public class ScenarioRunServiceTests
{
    private static ScenarioReport Example()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !Directory.Exists(Path.Combine(directory.FullName, "contracts", "scenario")))
        {
            directory = directory.Parent;
        }

        Assert.NotNull(directory);
        var json = File.ReadAllText(Path.Combine(directory!.FullName, "contracts", "scenario", "examples", "report.json"));
        return JsonSerializer.Deserialize<ScenarioReport>(json)!;
    }

    private static ScenarioRunService NewService() =>
        new(new InMemoryScenarioRunStore(10), new FakeTimeProvider(new DateTimeOffset(2026, 9, 22, 12, 0, 0, TimeSpan.Zero)));

    [Fact]
    public async Task The_runners_own_report_is_stored_whole_and_summarised()
    {
        var runs = NewService();

        var summary = await runs.IngestAsync(new IngestScenarioRunRequest("abc123 main", Example()), "ci");
        var stored = await runs.GetAsync(summary.Id);

        Assert.Equal(("reference", false, 2, 2), (summary.Sut, summary.Ok, summary.ScenarioCount, summary.SeedCount));
        Assert.Equal(new ScenarioCounts(1, 0, 1, 0), summary.Counts);
        Assert.Contains("battery_blind", summary.SurvivingMutants);
        Assert.Equal("ci", summary.SubmittedBy);
        Assert.Equal(Example().Scenarios[0].Runs[0].Assertions.Count, stored!.Report.Scenarios[0].Runs[0].Assertions.Count);
        Assert.Equal([summary.Id], (await runs.RecentAsync(5)).Select(r => r.Id));
    }

    [Fact]
    public async Task A_report_that_is_not_the_contract_is_refused_with_every_reason()
    {
        var runs = NewService();
        var report = Example() with { Version = 2, Sut = " ", Seeds = [] };

        var refused = await Assert.ThrowsAsync<ScenarioRunValidationException>(() =>
            runs.IngestAsync(new IngestScenarioRunRequest(new string('x', 201), report), null));

        Assert.Equal(4, refused.Errors.Count);
        await Assert.ThrowsAsync<ScenarioRunValidationException>(() =>
            runs.IngestAsync(new IngestScenarioRunRequest("no report", null), null));
    }

    [Fact]
    public void A_comparison_names_regressions_fixes_and_how_the_measurements_moved()
    {
        var before = Example();
        var lanes = before.Scenarios.Single(s => s.Name == "waypoint_lanes");
        var slower = lanes with
        {
            Outcome = "failed",
            Runs = [.. lanes.Runs.Select(run => run with
            {
                Assertions = [.. run.Assertions.Select(a => a.Measured is { } m ? a with { Measured = m + 2 } : a)],
            })],
        };
        var added = lanes with { Name = "new_scenario" };
        var after = before with
        {
            Scenarios = [slower, before.Scenarios.Single(s => s.Name == "v_formation_from_pads") with { Outcome = "xpass" }, added],
            Mutation = before.Mutation! with { Survivors = [.. before.Mutation!.Survivors.Skip(1), "brand_new_mutant"] },
        };
        var baseRun = new ScenarioRun(Guid.NewGuid(), DateTimeOffset.UnixEpoch, "base", null, before);
        var headRun = new ScenarioRun(Guid.NewGuid(), DateTimeOffset.UnixEpoch, "head", null, after);

        var comparison = ScenarioRunService.Compare(baseRun, headRun);

        var byName = comparison.Scenarios.ToDictionary(s => s.Name);
        Assert.Equal("regressed", byName["waypoint_lanes"].Change);
        Assert.Equal("regressed", byName["v_formation_from_pads"].Change); // xfail -> xpass: the suite no longer meets it
        Assert.Equal("added", byName["new_scenario"].Change);
        var completion = byName["waypoint_lanes"].Measurements.First(m => m.BaseMean is not null);
        Assert.Equal(2.0, completion.Delta);
        Assert.Equal(["brand_new_mutant"], comparison.NewSurvivors);
        Assert.Equal([before.Mutation.Survivors[0]], comparison.NoLongerSurviving);
    }
}
