using Microsoft.Extensions.Logging.Abstractions;
using SwarmApi.Application.Contracts;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Infrastructure.Tests;

/// <summary>One JSON file per run: written before it is acknowledged, found again after a restart, bounded.</summary>
public sealed class FileScenarioRunStoreTests : IDisposable
{
    private readonly string _directory = Path.Combine(Path.GetTempPath(), $"swarmsim-runs-{Guid.NewGuid():N}");

    public void Dispose()
    {
        if (Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }
    }

    private static ScenarioRun Run(string label, int minutes) => new(
        Guid.NewGuid(),
        new DateTimeOffset(2026, 9, 22, 12, minutes, 0, TimeSpan.Zero),
        label,
        null,
        new ScenarioReport(
            1, "reference", [1], true, new ScenarioCounts(1, 0, 0, 0), [],
            [new ScenarioResult("lanes", null, "d", "pass", null, "passed", null,
                [new ScenarioSeedRun(1, true, 0.1, [new AssertionResult("mission_completes", true, 24.8, "s", [])])])],
            null));

    [Fact]
    public async Task A_run_is_on_disk_once_stored_and_found_again_after_a_restart()
    {
        var first = new FileScenarioRunStore(_directory, 10, NullLogger.Instance);
        var older = Run("older", 0);
        var newer = Run("newer", 1);
        await first.AddAsync(older);
        await first.AddAsync(newer);

        var restarted = new FileScenarioRunStore(_directory, 10, NullLogger.Instance);

        Assert.Equal(2, Directory.GetFiles(_directory, "*.json").Length);
        Assert.Empty(Directory.GetFiles(_directory, "*.tmp"));
        Assert.Equal(["newer", "older"], (await restarted.RecentAsync(10)).Select(r => r.Label));
        var read = await restarted.GetAsync(older.Id);
        Assert.Equal(24.8, read!.Report.Scenarios[0].Runs[0].Assertions[0].Measured);
        Assert.Null(await restarted.GetAsync(Guid.NewGuid()));
    }

    [Fact]
    public async Task Past_the_limit_the_oldest_run_is_deleted()
    {
        var store = new FileScenarioRunStore(_directory, 2, NullLogger.Instance);

        var oldest = Run("oldest", 0);
        await store.AddAsync(oldest);
        await store.AddAsync(Run("middle", 1));
        await store.AddAsync(Run("newest", 2));

        Assert.Equal(2, store.Count);
        Assert.Equal(2, Directory.GetFiles(_directory, "*.json").Length);
        Assert.Null(await store.GetAsync(oldest.Id));
    }

    [Fact]
    public void A_directory_that_cannot_be_written_stops_startup()
    {
        Directory.CreateDirectory(_directory);
        var blocker = Path.Combine(_directory, "a-file");
        File.WriteAllText(blocker, "not a directory");

        var refused = Assert.Throws<InvalidOperationException>(() =>
            new FileScenarioRunStore(Path.Combine(blocker, "runs"), 10, NullLogger.Instance));

        Assert.Contains("ScenarioRuns:Directory", refused.Message);
    }
}
