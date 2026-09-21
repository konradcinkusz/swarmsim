using System.Net.WebSockets;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.IdentityModel.Tokens;
using SwarmApi.Application;
using SwarmApi.Domain;

namespace SwarmApi.Infrastructure;

public static class ServiceCollectionExtensions
{
    /// <summary>
    /// Registers <see cref="ISwarmBridge"/>: probes <c>RosBridge:Url</c> with a short
    /// timeout and registers <see cref="RosBridgeSwarmBridge"/> on success, or
    /// <see cref="SimulatedSwarmBridge"/> otherwise (P8). This is the one place that
    /// decision is made — see docs/adr/0003-rosbridge-degrade-pattern.md.
    /// </summary>
    public static async Task<IServiceCollection> AddSwarmBridgeAsync(
        this IServiceCollection services,
        IConfiguration configuration,
        ILogger logger,
        CancellationToken cancellationToken = default)
    {
        var options = configuration.GetSection(RosBridgeOptions.SectionName).Get<RosBridgeOptions>()
            ?? new RosBridgeOptions();

        if (!string.IsNullOrWhiteSpace(options.Url) && Uri.TryCreate(options.Url, UriKind.Absolute, out var uri))
        {
            var socket = new ClientWebSocket();
            using var timeoutCts = new CancellationTokenSource(TimeSpan.FromSeconds(options.ConnectTimeoutSeconds));
            using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);

            try
            {
                await socket.ConnectAsync(uri, linkedCts.Token);

                var bridge = new RosBridgeSwarmBridge(uri, socket);
                await bridge.StartAsync(cancellationToken);

                services.AddSingleton<ISwarmBridge>(bridge);
                logger.LogInformation("RosBridge reachable at {Url}; running in Connected mode.", uri);
                return services;
            }
            catch (Exception ex) when (ex is WebSocketException or OperationCanceledException)
            {
                socket.Dispose();
                logger.LogWarning(
                    ex, "RosBridge unreachable at {Url}; falling back to Simulated mode.", uri);
            }
        }
        else
        {
            logger.LogInformation("RosBridge:Url not configured; running in Simulated mode.");
        }

        services.AddSingleton<ISwarmBridge, SimulatedSwarmBridge>();
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
    /// activate. This is the one place the mode decision is made — see
    /// docs/adr/0005-mcp-server-and-bearer-auth.md. Callers read the resolved
    /// <see cref="AuthStatus"/> (DI singleton) to decide which endpoints to gate; this
    /// method never touches routing itself.
    /// </summary>
    public static IServiceCollection AddSwarmAuthentication(
        this IServiceCollection services, IConfiguration configuration, ILogger logger)
    {
        var options = configuration.GetSection(AuthOptions.SectionName).Get<AuthOptions>()
            ?? new AuthOptions();

        services.AddAuthorization();

        if (string.IsNullOrWhiteSpace(options.Authority))
        {
            logger.LogInformation("Auth:Authority not configured; running in Open mode (no authentication).");
            services.AddAuthentication();
            services.AddSingleton(new AuthStatus(AuthMode.Open));
            return services;
        }

        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(bearerOptions =>
            {
                bearerOptions.MetadataAddress = $"{options.Authority.TrimEnd('/')}/.well-known/openid-configuration";
                bearerOptions.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidIssuer = options.Issuer,
                    ValidAudience = options.Audience,
                    ValidateIssuerSigningKey = true,
                };
            });
        services.AddSingleton(new AuthStatus(AuthMode.Enforced));

        logger.LogInformation(
            "Auth:Authority set to {Authority}; running in Enforced mode.", options.Authority);
        return services;
    }
}
