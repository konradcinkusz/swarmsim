using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Authorization;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Logging;
using Microsoft.IdentityModel.Tokens;
using SwarmApi.Application;
using SwarmApi.Domain;

namespace SwarmApi.Infrastructure;

public static class ServiceCollectionExtensions
{
    /// <summary>
    /// Registers <see cref="ISwarmBridge"/> from configuration alone (P8, docs/adr/0003 and
    /// its 2026-09-22 amendment): a <c>ws://</c>/<c>wss://</c> <c>RosBridge:Url</c> selects
    /// <see cref="RosBridgeSwarmBridge"/>, connected and reconnected in the background by
    /// <see cref="RosBridgeConnectionService"/>; no URL selects <see cref="SimulatedSwarmBridge"/>.
    /// A configured but unreachable swarm is never replaced by a simulated one — it reports
    /// Disconnected until it answers, so an operator cannot mistake stand-in drones for real
    /// ones — and a configured URL that is not a WebSocket URL stops startup for the same
    /// reason. This is the one place that decision is made.
    /// </summary>
    /// <exception cref="InvalidOperationException"><c>RosBridge:Url</c> is set but is not a ws:// or wss:// URL.</exception>
    public static IServiceCollection AddSwarmBridge(
        this IServiceCollection services, IConfiguration configuration, ILogger logger)
    {
        var options = configuration.GetSection(RosBridgeOptions.SectionName).Get<RosBridgeOptions>()
            ?? new RosBridgeOptions();
        services.TryAddSingleton(TimeProvider.System);

        if (!string.IsNullOrWhiteSpace(options.Url))
        {
            if (!Uri.TryCreate(options.Url, UriKind.Absolute, out var uri) || uri.Scheme is not ("ws" or "wss"))
            {
                // Falling back to the simulated swarm here would put stand-in drones in front
                // of an operator who asked for real ones; a typo must fail loudly instead.
                throw new InvalidOperationException(
                    $"RosBridge:Url '{options.Url}' is not a ws:// or wss:// URL. Fix it, or unset it to run the simulated swarm.");
            }

            services.AddSingleton(sp => new RosBridgeSwarmBridge(
                uri,
                options,
                sp.GetRequiredService<TimeProvider>(),
                sp.GetRequiredService<ILogger<RosBridgeSwarmBridge>>()));
            services.AddSingleton<ISwarmBridge>(sp => sp.GetRequiredService<RosBridgeSwarmBridge>());
            services.AddHostedService<RosBridgeConnectionService>();
            logger.LogInformation(
                "RosBridge:Url is {Url}: connecting in the background; /health reports Connected or Disconnected.", uri);
            return services;
        }

        logger.LogInformation("RosBridge:Url not configured; running in Simulated mode.");
        services.AddSingleton<ISwarmBridge>(sp => new SimulatedSwarmBridge(sp.GetRequiredService<TimeProvider>()));
        return services;
    }

    /// <summary>
    /// Registers JWT bearer authentication against an external `authservice` instance
    /// (RS256, JWKS discovery via `/.well-known/openid-configuration`) when
    /// <c>Auth:Authority</c> is configured; otherwise registers the authentication
    /// service infrastructure with no scheme and reports <see cref="AuthMode.Open"/>
    /// (P8) — every endpoint stays reachable with no token, exactly as before this
    /// dependency existed. `Program.cs` calls `app.UseAuthentication()` unconditionally
    /// (it needs to run for Enforced mode to work at all), and that middleware requires
    /// `IAuthenticationSchemeProvider` to be registered regardless of mode — hence the
    /// parameterless `AddAuthentication()` call below in Open mode: no scheme, so
    /// nothing to actually authenticate against, but the middleware has something to
    /// activate. In Enforced mode a fallback authorization policy makes every endpoint
    /// require a token unless it is explicitly AllowAnonymous. This is the one place the
    /// mode decision is made — see docs/adr/0005-mcp-server-and-bearer-auth.md.
    /// </summary>
    public static IServiceCollection AddSwarmAuthentication(
        this IServiceCollection services, IConfiguration configuration, ILogger logger)
    {
        var options = configuration.GetSection(AuthOptions.SectionName).Get<AuthOptions>()
            ?? new AuthOptions();

        if (string.IsNullOrWhiteSpace(options.Authority))
        {
            if (options.Required)
            {
                throw new InvalidOperationException(
                    "Auth:Required is set but Auth:Authority is not. This deployment must run Enforced: " +
                    "set Auth:Authority to an authservice instance (docs/adr/0011).");
            }

            logger.LogInformation("Auth:Authority not configured; running in Open mode (no authentication).");
            services.AddAuthorization();
            services.AddAuthentication();
            services.AddSingleton(new AuthStatus(AuthMode.Open));
            return services;
        }

        // Deny by default (architecture-standards SECURITY-REVIEW): once a token authority
        // exists, every endpoint requires an authenticated caller unless it opts out with
        // AllowAnonymous. The open list is short and lives next to the endpoints it opens
        // (health probes, swarm and mission reads — docs/adr/0005); a new endpoint that
        // forgets to say anything is protected, not exposed.
        services.AddAuthorization(authorization => authorization.FallbackPolicy =
            new AuthorizationPolicyBuilder(JwtBearerDefaults.AuthenticationScheme).RequireAuthenticatedUser().Build());

        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(bearerOptions =>
            {
                bearerOptions.MetadataAddress = $"{options.Authority.TrimEnd('/')}/.well-known/openid-configuration";
                bearerOptions.RequireHttpsMetadata = options.RequireHttpsMetadata;
                bearerOptions.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidIssuer = options.Issuer,
                    ValidAudience = options.Audience,
                    ValidateIssuerSigningKey = true,
                };
            });
        services.AddSingleton(new AuthStatus(AuthMode.Enforced));

        if (!options.RequireHttpsMetadata)
        {
            logger.LogWarning(
                "Auth:RequireHttpsMetadata is false: token signing keys for {Authority} are fetched without TLS. " +
                "Acceptable only inside a private network such as the local compose `auth` profile.",
                options.Authority);
        }

        logger.LogInformation(
            "Auth:Authority set to {Authority}; running in Enforced mode.", options.Authority);
        return services;
    }

    /// <summary>
    /// Where scenario runs are kept (docs/adr/0011): a directory of JSON files when
    /// <c>ScenarioRuns:Directory</c> is set — and writable, or startup stops — else memory,
    /// logged and reported by <c>/health</c> so nobody mistakes it for storage (P8).
    /// </summary>
    /// <exception cref="InvalidOperationException"><c>ScenarioRuns:Directory</c> is set but not writable.</exception>
    public static IServiceCollection AddScenarioRunStore(
        this IServiceCollection services, IConfiguration configuration, ILogger logger)
    {
        var options = configuration.GetSection(ScenarioRunOptions.SectionName).Get<ScenarioRunOptions>()
            ?? new ScenarioRunOptions();
        if (string.IsNullOrWhiteSpace(options.Directory))
        {
            logger.LogInformation(
                "ScenarioRuns:Directory not configured; scenario runs are kept in memory and forgotten on restart.");
            services.AddSingleton<IScenarioRunStore>(new InMemoryScenarioRunStore(options.MaxRuns));
        }
        else
        {
            services.AddSingleton<IScenarioRunStore>(new FileScenarioRunStore(options.Directory, options.MaxRuns, logger));
        }

        return services;
    }
}
