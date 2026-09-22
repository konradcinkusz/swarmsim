namespace SwarmApi.Api.Idempotency;

/// <summary>
/// Remembers what each idempotent write answered, per caller and key, for
/// <see cref="Retention"/>. In memory and bounded — the same stance as the mission log
/// (DEVIATIONS.md, P3/P4 row): a restart forgets, and a replay after one runs the write again.
/// </summary>
public sealed class IdempotencyStore(TimeProvider time, int capacity = 10_000)
{
    public static readonly TimeSpan Retention = TimeSpan.FromHours(24);

    private readonly object _lock = new();
    private readonly Dictionary<string, Entry> _entries = new();
    private readonly LinkedList<string> _order = new();

    public enum Outcome
    {
        /// <summary>First time this key is seen: run the request, then Complete or Abandon.</summary>
        Started,

        /// <summary>Seen and answered: replay the stored response instead of running it again.</summary>
        Replay,

        /// <summary>Seen, still running: the caller must wait, not run it twice.</summary>
        InFlight,

        /// <summary>Seen with a different request: the key was reused for something else.</summary>
        Mismatch,
    }

    public sealed record StoredResponse(int StatusCode, string? Body, string ContentType, string? Location);

    public (Outcome Outcome, StoredResponse? Response) Begin(string scope, string fingerprint)
    {
        lock (_lock)
        {
            var now = time.GetUtcNow();
            if (_entries.TryGetValue(scope, out var entry) && now - entry.CreatedUtc <= Retention)
            {
                if (entry.Fingerprint != fingerprint)
                {
                    return (Outcome.Mismatch, null);
                }

                return entry.Response is null ? (Outcome.InFlight, null) : (Outcome.Replay, entry.Response);
            }

            if (entry is not null)
            {
                _entries.Remove(scope);
                _order.Remove(scope);
            }

            _entries[scope] = new Entry(fingerprint, now);
            _order.AddLast(scope);
            while (_entries.Count > capacity && _order.First is { } oldest)
            {
                _entries.Remove(oldest.Value);
                _order.RemoveFirst();
            }

            return (Outcome.Started, null);
        }
    }

    public void Complete(string scope, StoredResponse response)
    {
        lock (_lock)
        {
            if (_entries.TryGetValue(scope, out var entry))
            {
                entry.Response = response;
            }
        }
    }

    /// <summary>Forgets a key whose request failed without a definite answer, so a retry runs it again.</summary>
    public void Abandon(string scope)
    {
        lock (_lock)
        {
            if (_entries.Remove(scope))
            {
                _order.Remove(scope);
            }
        }
    }

    private sealed class Entry(string fingerprint, DateTimeOffset createdUtc)
    {
        public string Fingerprint { get; } = fingerprint;

        public DateTimeOffset CreatedUtc { get; } = createdUtc;

        public StoredResponse? Response { get; set; }
    }
}
