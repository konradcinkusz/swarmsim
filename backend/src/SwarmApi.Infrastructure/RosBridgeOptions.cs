namespace SwarmApi.Infrastructure;

/// <summary>Bound from the <c>RosBridge</c> configuration section (env var: <c>RosBridge__Url</c>).</summary>
public sealed class RosBridgeOptions
{
    public const string SectionName = "RosBridge";

    /// <summary>rosbridge_suite WebSocket URL, e.g. <c>ws://sim:9090</c>. Null/empty means "no bridge configured".</summary>
    public string? Url { get; set; }

    /// <summary>How long to wait for the initial connection before falling back to <see cref="SimulatedSwarmBridge"/>.</summary>
    public double ConnectTimeoutSeconds { get; set; } = 3.0;
}
