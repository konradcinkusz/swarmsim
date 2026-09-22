using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Mvc.Testing;
using SwarmApi.Application.Contracts;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>Stored scenario runs over HTTP (docs/adr/0011), fed the report contract's own example.</summary>
public class ScenarioRunEndpointTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private static JsonNode ExampleReport()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !Directory.Exists(Path.Combine(directory.FullName, "contracts", "scenario")))
        {
            directory = directory.Parent;
        }

        Assert.NotNull(directory);
        return JsonNode.Parse(File.ReadAllText(
            Path.Combine(directory!.FullName, "contracts", "scenario", "examples", "report.json")))!;
    }

    private static StringContent Ingest(string label, JsonNode report) => new(
        new JsonObject { ["label"] = label, ["report"] = report }.ToJsonString(), Encoding.UTF8, "application/json");

    [Fact]
    public async Task A_report_is_stored_listed_read_back_and_compared()
    {
        var client = factory.CreateClient();
        var baseReport = ExampleReport();
        var headReport = ExampleReport();
        headReport["scenarios"]![0]!["outcome"] = "failed";

        var first = await client.PostAsync("/api/scenario-runs", Ingest("base", baseReport));
        var second = await client.PostAsync("/api/scenario-runs", Ingest("head", headReport));
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        var baseRun = (await first.Content.ReadFromJsonAsync<ScenarioRunSummary>(TestJson.Options))!;
        var headRun = (await second.Content.ReadFromJsonAsync<ScenarioRunSummary>(TestJson.Options))!;
        Assert.Equal($"/api/scenario-runs/{baseRun.Id}", first.Headers.Location!.OriginalString);

        var listed = await client.GetFromJsonAsync<List<ScenarioRunSummary>>("/api/scenario-runs", TestJson.Options);
        var stored = await client.GetFromJsonAsync<JsonNode>($"/api/scenario-runs/{baseRun.Id}");
        var comparison = await client.GetFromJsonAsync<ScenarioRunComparison>(
            $"/api/scenario-runs/compare?base={baseRun.Id}&head={headRun.Id}", TestJson.Options);

        Assert.Contains(listed!, r => r.Id == headRun.Id && r.Label == "head");
        // Stored whole, in the runner's own snake_case: the report reads back as the contract.
        static List<(string?, double?)> Measured(JsonNode report) =>
            report["scenarios"]![0]!["runs"]![0]!["assertions"]!.AsArray()
                .Select(a => (a!["assertion"]!.GetValue<string>(), a["measured"]?.GetValue<double>()))
                .ToList();
        Assert.Equal(Measured(baseReport), Measured(stored!["report"]!));
        Assert.NotNull(stored["report"]!["scenarios"]![0]!["killed_mutants"]);
        Assert.Equal("regressed", comparison!.Scenarios.Single(s => s.Name == "waypoint_lanes").Change);
        Assert.Equal(
            HttpStatusCode.NotFound,
            (await client.GetAsync($"/api/scenario-runs/compare?base={baseRun.Id}&head={Guid.NewGuid()}")).StatusCode);
    }

    [Fact]
    public async Task A_report_that_is_not_the_contract_is_a_400_listing_why()
    {
        var client = factory.CreateClient();
        var report = ExampleReport();
        report["version"] = 7;

        var response = await client.PostAsync("/api/scenario-runs", Ingest("bad", report));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("report.version", await response.Content.ReadAsStringAsync());
    }
}
