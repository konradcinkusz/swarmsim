using System.Security.Claims;

namespace SwarmApi.Api;

/// <summary>Who is calling, as far as the API knows.</summary>
public static class Caller
{
    /// <summary>
    /// The token's subject in Enforced mode; null in Open mode, where nobody is identified.
    /// JwtBearer maps <c>sub</c> to <see cref="ClaimTypes.NameIdentifier"/> by default, so both are read.
    /// </summary>
    public static string? Subject(ClaimsPrincipal user) =>
        user.Identity?.IsAuthenticated == true
            ? user.FindFirst(ClaimTypes.NameIdentifier)?.Value ?? user.FindFirst("sub")?.Value ?? user.Identity.Name
            : null;
}
