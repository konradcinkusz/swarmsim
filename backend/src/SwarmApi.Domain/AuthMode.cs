namespace SwarmApi.Domain;

/// <summary>
/// Whether <c>SwarmApi.Api</c> is enforcing bearer-token authentication against an
/// external `authservice` instance — the P8 "visible degradation" value for that
/// dependency, reported by <c>GET /health</c>. See
/// docs/adr/0005-mcp-server-and-bearer-auth.md.
/// </summary>
public enum AuthMode
{
    Open,
    Enforced,
}
