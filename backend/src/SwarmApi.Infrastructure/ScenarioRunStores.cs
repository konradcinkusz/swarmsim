using System.Text.Json;
using Microsoft.Extensions.Logging;
using SwarmApi.Application;
using SwarmApi.Application.Contracts;

namespace SwarmApi.Infrastructure;

/// <summary>The <c>ScenarioRuns</c> configuration section (docs/adr/0011).</summary>
public sealed class ScenarioRunOptions
{
    public const string SectionName = "ScenarioRuns";

    /// <summary>
    /// Where each run is written as its own JSON file. Unset: runs are kept in memory and
    /// forgotten on restart (P8's fallback, reported by <c>/health</c>). Set but not
    /// writable: startup stops — a configured store that silently kept nothing would be worse.
    /// </summary>
    public string? Directory { get; set; }

    /// <summary>How many runs are kept; past it the oldest is deleted to make room.</summary>
    public int MaxRuns { get; set; } = 1000;
}

/// <summary>Runs in memory, the most recent <c>MaxRuns</c> of them.</summary>
public sealed class InMemoryScenarioRunStore(int maxRuns) : IScenarioRunStore
{
    private readonly object _lock = new();
    private readonly LinkedList<ScenarioRun> _runs = new();

    public string Mode => "InMemory";

    public int Count
    {
        get
        {
            lock (_lock)
            {
                return _runs.Count;
            }
        }
    }

    public Task AddAsync(ScenarioRun run, CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            _runs.AddFirst(run);
            while (_runs.Count > maxRuns)
            {
                _runs.RemoveLast();
            }
        }

        return Task.CompletedTask;
    }

    public Task<ScenarioRun?> GetAsync(Guid id, CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            return Task.FromResult(_runs.FirstOrDefault(r => r.Id == id));
        }
    }

    public Task<IReadOnlyList<ScenarioRunSummary>> RecentAsync(int limit, CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            return Task.FromResult<IReadOnlyList<ScenarioRunSummary>>(_runs.Take(limit).Select(r => r.Summary()).ToList());
        }
    }
}

/// <summary>
/// One JSON file per run in a directory — on Fly.io, a volume. A run is written in full
/// before it is acknowledged (temporary file, then an atomic rename), so a 201 means it is
/// on disk. On start the directory is indexed, newest first, up to <c>MaxRuns</c>; runs are
/// read back from disk when asked for. Deliberately not a database: runs are immutable
/// documents, read one at a time, by one machine. The trigger for Postgres is a second
/// machine or per-tenant storage — docs/architecture/DEVIATIONS.md, P3/P4.
/// </summary>
public sealed class FileScenarioRunStore : IScenarioRunStore
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    private readonly string _directory;
    private readonly int _maxRuns;
    private readonly object _lock = new();
    private readonly LinkedList<(ScenarioRunSummary Summary, string Path)> _index = new();

    public FileScenarioRunStore(string directory, int maxRuns, ILogger logger)
    {
        _directory = Path.GetFullPath(directory);
        _maxRuns = maxRuns;
        EnsureWritable(_directory);

        var loaded = 0;
        foreach (var path in System.IO.Directory.EnumerateFiles(_directory, "*.json").OrderDescending())
        {
            if (loaded == maxRuns)
            {
                break;
            }

            try
            {
                var run = JsonSerializer.Deserialize<ScenarioRun>(File.ReadAllBytes(path), Json);
                if (run is not null)
                {
                    _index.AddLast((run.Summary(), path));
                    loaded++;
                }
            }
            catch (JsonException exception)
            {
                logger.LogWarning(exception, "Skipping unreadable scenario run file {Path}", path);
            }
        }

        logger.LogInformation("Scenario runs: File — {Count} run(s) in {Directory}", loaded, _directory);
    }

    public string Mode => "File";

    public int Count
    {
        get
        {
            lock (_lock)
            {
                return _index.Count;
            }
        }
    }

    public async Task AddAsync(ScenarioRun run, CancellationToken cancellationToken = default)
    {
        // The name sorts by arrival, so the start-up index needs no parsing to be newest-first.
        var path = Path.Combine(_directory, $"{run.ReceivedAtUtc.UtcDateTime:yyyyMMddTHHmmssfffffff}-{run.Id:N}.json");
        var temporary = path + ".tmp";
        await File.WriteAllBytesAsync(temporary, JsonSerializer.SerializeToUtf8Bytes(run, Json), cancellationToken);
        File.Move(temporary, path, overwrite: false);

        var evicted = new List<string>();
        lock (_lock)
        {
            _index.AddFirst((run.Summary(), path));
            while (_index.Count > _maxRuns)
            {
                evicted.Add(_index.Last!.Value.Path);
                _index.RemoveLast();
            }
        }

        foreach (var old in evicted)
        {
            File.Delete(old);
        }
    }

    public async Task<ScenarioRun?> GetAsync(Guid id, CancellationToken cancellationToken = default)
    {
        string? path;
        lock (_lock)
        {
            path = _index.FirstOrDefault(entry => entry.Summary.Id == id).Path;
        }

        if (path is null || !File.Exists(path))
        {
            return null;
        }

        await using var stream = File.OpenRead(path);
        return await JsonSerializer.DeserializeAsync<ScenarioRun>(stream, Json, cancellationToken);
    }

    public Task<IReadOnlyList<ScenarioRunSummary>> RecentAsync(int limit, CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            return Task.FromResult<IReadOnlyList<ScenarioRunSummary>>(_index.Take(limit).Select(e => e.Summary).ToList());
        }
    }

    private static void EnsureWritable(string directory)
    {
        var probe = Path.Combine(directory, $".write-probe-{Guid.NewGuid():N}");
        try
        {
            System.IO.Directory.CreateDirectory(directory);
            File.WriteAllText(probe, "ok");
            File.Delete(probe);
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            throw new InvalidOperationException(
                $"ScenarioRuns:Directory '{directory}' is not writable. Fix it, or unset it to keep runs in memory.",
                exception);
        }
    }
}
