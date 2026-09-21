namespace SwarmApi.Infrastructure;

/// <summary>Bound from the <c>Auth</c> configuration section (env var: <c>Auth__Authority</c>).</summary>
public sealed class AuthOptions
{
    public const string SectionName = "Auth";

    /// <summary>
    /// Base URL of an <c>authservice</c> instance, e.g. <c>https://your-authservice.fly.dev</c>.
    /// Null/empty means "no authority configured" — <see cref="ServiceCollectionExtensions.AddSwarmAuthentication"/>
    /// then runs in Open mode (P8), same as today.
    /// </summary>
    public string? Authority { get; set; }

    /// <summary>JWT audience this deployment validates. Must match the audience `authservice` issues tokens for (its `Jwt:Audience`).</summary>
    public string Audience { get; set; } = "SwarmApi";

    /// <summary>JWT issuer this deployment validates. Must match `authservice`'s `Jwt:Issuer`.</summary>
    public string Issuer { get; set; } = "AuthService";
}
