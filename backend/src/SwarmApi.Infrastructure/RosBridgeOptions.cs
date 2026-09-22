namespace SwarmApi.Infrastructure;

/// <summary>Bound from the <c>RosBridge</c> configuration section (env var: <c>RosBridge__Url</c>).</summary>
public sealed class RosBridgeOptions
{
    public const string SectionName = "RosBridge";

    /// <summary>
    /// rosbridge_suite WebSocket URL, e.g. <c>ws://sim:9090</c>. Null/empty means "no real
    /// swarm": the in-memory simulated bridge stands in. Set, the real bridge is used even
    /// while the URL is unreachable — it reports Disconnected and keeps retrying rather than
    /// swapping in a simulated swarm an operator could mistake for the real one.
    /// </summary>
    public string? Url { get; set; }

    /// <summary>How long one connection attempt may take before it counts as failed.</summary>
    public double ConnectTimeoutSeconds { get; set; } = 3.0;

    /// <summary>First retry delay after a failed or dropped connection; doubles per failure.</summary>
    public double ReconnectInitialDelaySeconds { get; set; } = 1.0;

    /// <summary>Upper bound for the doubling retry delay.</summary>
    public double ReconnectMaxDelaySeconds { get; set; } = 30.0;

    /// <summary>A single rosbridge message larger than this is dropped rather than buffered without limit.</summary>
    public int MaxMessageBytes { get; set; } = 1024 * 1024;
}
