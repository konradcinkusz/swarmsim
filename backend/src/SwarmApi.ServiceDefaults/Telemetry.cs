using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using OpenTelemetry;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

namespace SwarmApi.ServiceDefaults;

/// <summary>
/// OpenTelemetry for the service (P15): traces, metrics and logs, exported over OTLP to
/// whatever <c>OTEL_EXPORTER_OTLP_ENDPOINT</c> names (protocol, headers and the rest from
/// the standard <c>OTEL_EXPORTER_OTLP_*</c> variables). With no endpoint nothing is
/// exported and nothing fails: the instrumentation still runs in-process, and
/// <c>/health</c> and the startup log say telemetry is <c>Off</c> — the same visible
/// degradation as every other optional dependency (P8). Probe requests are left out of
/// traces so they do not drown the rest.
/// </summary>
public static class Telemetry
{
    public const string EndpointVariable = "OTEL_EXPORTER_OTLP_ENDPOINT";
    public const string HealthCheckName = "telemetry";

    /// <param name="sources">The service's own <c>ActivitySource</c> and <c>Meter</c> names.</param>
    public static TBuilder AddTelemetry<TBuilder>(this TBuilder builder, params string[] sources)
        where TBuilder : IHostApplicationBuilder
    {
        var endpoint = builder.Configuration[EndpointVariable];
        var mode = string.IsNullOrWhiteSpace(endpoint) ? "Off" : "Otlp";

        builder.Logging.AddOpenTelemetry(logging =>
        {
            logging.IncludeFormattedMessage = true;
            logging.IncludeScopes = true;
        });

        var telemetry = builder.Services.AddOpenTelemetry()
            .ConfigureResource(resource => resource.AddService(builder.Environment.ApplicationName))
            .WithMetrics(metrics => metrics
                .AddAspNetCoreInstrumentation()
                .AddRuntimeInstrumentation()
                .AddMeter(sources))
            .WithTracing(tracing => tracing
                .AddAspNetCoreInstrumentation(options => options.Filter = context => !IsProbe(context.Request.Path))
                .AddSource(sources));
        if (mode == "Otlp")
        {
            telemetry.UseOtlpExporter();
        }

        builder.Services.AddHealthChecks().AddCheck(
            HealthCheckName,
            () => HealthCheckResult.Healthy(
                $"Telemetry: {mode}", new Dictionary<string, object> { ["telemetry"] = mode }),
            tags: ["live"]);
        builder.Services.AddHostedService(provider => new TelemetryModeLog(
            provider.GetRequiredService<ILoggerFactory>().CreateLogger("Startup"), mode, endpoint));
        return builder;
    }

    private static bool IsProbe(PathString path) =>
        path.StartsWithSegments("/health") || path.StartsWithSegments("/alive");

    /// <summary>The startup line naming the telemetry mode, next to the bridge and auth ones.</summary>
    private sealed class TelemetryModeLog(ILogger logger, string mode, string? endpoint) : IHostedService
    {
        public Task StartAsync(CancellationToken cancellationToken)
        {
            if (mode == "Otlp")
            {
                logger.LogInformation("Telemetry: Otlp — traces, metrics and logs to {Endpoint}", endpoint);
            }
            else
            {
                logger.LogInformation("Telemetry: Off — {Variable} is not set; nothing is exported", EndpointVariable);
            }

            return Task.CompletedTask;
        }

        public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
    }
}
