namespace SwarmApi.Application.Tests;

/// <summary>A manually-advanced clock, so simulated-swarm-movement tests are deterministic instead of wall-clock-timed.</summary>
internal sealed class FakeTimeProvider(DateTimeOffset start) : TimeProvider
{
    private DateTimeOffset _now = start;

    public override DateTimeOffset GetUtcNow() => _now;

    public void Advance(TimeSpan by) => _now += by;
}
