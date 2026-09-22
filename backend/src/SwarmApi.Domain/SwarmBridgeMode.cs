namespace SwarmApi.Domain;

/// <summary>
/// Which <c>ISwarmBridge</c> is active and, for the real one, whether it currently has a
/// connection — the P8 "visible degradation" value reported by <c>GET /health</c>, the
/// swarm state and the dashboard. See docs/adr/0003 and its 2026-09-22 amendments.
/// </summary>
public enum SwarmBridgeMode
{
    /// <summary>The rosbridge connection is up and state is flowing.</summary>
    Connected,

    /// <summary>No rosbridge URL is configured: an in-memory swarm stands in.</summary>
    Simulated,

    /// <summary>A rosbridge URL is configured but the connection is down; it is being retried.</summary>
    Disconnected,
}
