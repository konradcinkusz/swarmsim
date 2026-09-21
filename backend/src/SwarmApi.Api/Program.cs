using System.Text.Json.Serialization;
using SwarmApi.Api;
using SwarmApi.Api.Endpoints;
using SwarmApi.Application;
using SwarmApi.Domain;
using SwarmApi.Infrastructure;
using SwarmApi.ServiceDefaults;

var builder = WebApplication.CreateBuilder(args);

builder.AddServiceDefaults();

builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.Converters.Add(new JsonStringEnumConverter());
});

// Bootstrap logger for the one decision made before the DI container exists: which
// ISwarmBridge to register. The app's own logging (via AddServiceDefaults) takes over
// for everything after builder.Build().
using (var bootstrapLoggerFactory = LoggerFactory.Create(logging => logging.AddConsole()))
{
    var bootstrapLogger = bootstrapLoggerFactory.CreateLogger("Startup");
    await builder.Services.AddSwarmBridgeAsync(builder.Configuration, bootstrapLogger);
    builder.Services.AddSwarmAuthentication(builder.Configuration, bootstrapLogger);
}

builder.Services.AddSingleton<MissionService>();
builder.Services.AddHealthChecks()
    .AddCheck<SwarmBridgeHealthCheck>("swarm_bridge", tags: ["live"])
    .AddCheck<AuthHealthCheck>("auth", tags: ["live"]);

var app = builder.Build();

// AddSingleton<ISwarmBridge>(instance) registers a pre-built instance, which the
// built-in container does not dispose automatically (only container-created instances
// are). RosBridgeSwarmBridge owns a socket and a background loop, so its shutdown is
// wired explicitly here rather than silently relying on process exit to reclaim them.
if (app.Services.GetRequiredService<ISwarmBridge>() is IAsyncDisposable disposableBridge)
{
    app.Services.GetRequiredService<IHostApplicationLifetime>().ApplicationStopping.Register(
        () => disposableBridge.DisposeAsync().AsTask().GetAwaiter().GetResult());
}

app.UseCors(SwarmApi.ServiceDefaults.Extensions.FrontendCorsPolicy);
app.UseAuthentication();
app.UseAuthorization();
app.UseDefaultFiles();
app.UseStaticFiles();

var authStatus = app.Services.GetRequiredService<AuthStatus>();
app.MapDefaultEndpoints();
app.MapMissionEndpoints(requireAuthentication: authStatus.Mode == AuthMode.Enforced);
app.MapSwarmStateEndpoints();

app.Run();

// Exposes the entry point to SwarmApi.Api.Tests' WebApplicationFactory<Program>.
public partial class Program;
