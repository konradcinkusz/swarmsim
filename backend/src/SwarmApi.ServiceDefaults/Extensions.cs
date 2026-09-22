using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Diagnostics.HealthChecks;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;

namespace SwarmApi.ServiceDefaults;

/// <summary>
/// The shared kernel (P2): cross-cutting plumbing only (health checks, CORS). No
/// entity, DTO, or business rule belongs here — see the constitution's P2 ceiling.
/// A single-service repository still gets this now, ahead of needing a second
/// service, because it is what makes the next service cheap to add correctly; see
/// docs/adr/0002-composition-root-split.md for why there is no AppHost around it yet.
/// </summary>
public static class Extensions
{
    public const string FrontendCorsPolicy = "Frontend";

    public static TBuilder AddServiceDefaults<TBuilder>(this TBuilder builder)
        where TBuilder : IHostApplicationBuilder
    {
        builder.Services.AddHealthChecks();

        builder.Services.AddCors(options =>
        {
            options.AddPolicy(FrontendCorsPolicy, policy =>
            {
                var origins = builder.Configuration.GetSection("Cors:AllowedOrigins").Get<string[]>();
                if (origins is { Length: > 0 })
                {
                    policy.WithOrigins(origins).AllowAnyHeader().AllowAnyMethod();
                }
                else
                {
                    // No configured origins: the dashboard is served from this same
                    // origin (wwwroot), so same-origin `fetch` needs no CORS grant at
                    // all. This policy only matters once a separate frontend origin
                    // exists — configure Cors:AllowedOrigins then, rather than opening
                    // it to any origin by default.
                    policy.WithOrigins("http://localhost").AllowAnyHeader().AllowAnyMethod();
                }
            });
        });

        return builder;
    }

    /// <summary>Maps <c>/health</c> (readiness — every registered check) and <c>/alive</c> (liveness — `live`-tagged only).</summary>
    public static WebApplication MapDefaultEndpoints(this WebApplication app)
    {
        // Probes never carry a token: both stay reachable whatever a service's auth policy is.
        app.MapHealthChecks("/health", new HealthCheckOptions
        {
            ResponseWriter = WriteHealthResponseAsync,
        }).AllowAnonymous();

        app.MapHealthChecks("/alive", new HealthCheckOptions
        {
            Predicate = check => check.Tags.Contains("live"),
            ResponseWriter = WriteHealthResponseAsync,
        }).AllowAnonymous();

        return app;
    }

    private static Task WriteHealthResponseAsync(HttpContext context, HealthReport report)
    {
        context.Response.ContentType = "application/json";
        var payload = new
        {
            status = report.Status.ToString(),
            checks = report.Entries.ToDictionary(
                e => e.Key,
                e => new { status = e.Value.Status.ToString(), description = e.Value.Description, data = e.Value.Data }),
        };
        return context.Response.WriteAsJsonAsync(payload);
    }
}
