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

    /// <summary>
    /// Whether the authority's metadata/JWKS must be fetched over HTTPS (default: true).
    /// Only the local compose `auth` profile turns it off, because `authservice` serves
    /// plain http inside that network; left on there, JwtBearer refuses the http
    /// metadata address on the first gated request and the API answers 500.
    /// </summary>
    public bool RequireHttpsMetadata { get; set; } = true;

    /// <summary>
    /// Whether this deployment may run at all without an authority (default: false). A
    /// deployment anyone else can reach sets it (the Fly config does): there, Open mode
    /// would let any caller approve and dispatch a mission plan, so a missing
    /// <see cref="Authority"/> stops startup instead of degrading to Open
    /// (docs/adr/0009, docs/adr/0011).
    /// </summary>
    public bool Required { get; set; }
}
