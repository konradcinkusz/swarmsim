using System.Text.Json.Serialization;
using SwarmApi.Api;
using SwarmApi.Api.Endpoints;
using SwarmApi.Infrastructure;
using SwarmApi.ServiceDefaults;

var builder = WebApplication.CreateBuilder(args);

builder.AddServiceDefaults();

builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.Converters.Add(new JsonStringEnumConverter());
});

// Bootstrap logger for the decisions made before the DI container exists: which
// ISwarmBridge to register and which auth mode to run in. The app's own logging takes
// over for everything after builder.Build().
using (var bootstrapLoggerFactory = LoggerFactory.Create(logging => logging.AddConsole()))
{
    var bootstrapLogger = bootstrapLoggerFactory.CreateLogger("Startup");
    builder.Services.AddSwarmBridge(builder.Configuration, bootstrapLogger);
    builder.Services.AddSwarmAuthentication(builder.Configuration, bootstrapLogger);
}

builder.Services.AddSwarmMissions(builder.Configuration);
builder.Services.AddSwarmHealthChecks();

var app = builder.Build();

// Static files first: the dashboard is public (docs/adr/0005), and serving it ahead of
// authorization keeps the deny-by-default fallback policy from applying to it.
app.UseDefaultFiles();
app.UseStaticFiles();
app.UseCors(SwarmApi.ServiceDefaults.Extensions.FrontendCorsPolicy);
app.UseAuthentication();
app.UseAuthorization();

app.MapDefaultEndpoints();
app.MapMissionEndpoints();
app.MapMissionPlanEndpoints();
app.MapSwarmEndpoints();

app.Run();

// Exposes the entry point to SwarmApi.Api.Tests' WebApplicationFactory<Program>.
public partial class Program;
