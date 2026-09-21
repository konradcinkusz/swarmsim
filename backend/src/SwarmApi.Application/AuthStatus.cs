using SwarmApi.Domain;

namespace SwarmApi.Application;

/// <summary>
/// Read-only snapshot of which <see cref="AuthMode"/> is active, decided once at startup
/// by <c>SwarmApi.Infrastructure.ServiceCollectionExtensions.AddSwarmAuthentication</c>
/// and consumed by the health check and by <c>Program.cs</c> to decide which endpoints
/// require a token. See docs/adr/0005-mcp-server-and-bearer-auth.md.
/// </summary>
public sealed record AuthStatus(AuthMode Mode);
