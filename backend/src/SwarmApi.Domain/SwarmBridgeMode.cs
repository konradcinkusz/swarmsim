namespace SwarmApi.Domain;

/// <summary>
/// Which <c>ISwarmBridge</c> implementation is active — the P8 "visible degradation"
/// value: reported by <c>GET /health</c> and the startup log, per docs/adr/0003.
/// </summary>
public enum SwarmBridgeMode
{
    Connected,
    Simulated,
}
