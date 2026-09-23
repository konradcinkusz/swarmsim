using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.Routing;
using Microsoft.Extensions.DependencyInjection;
using SwarmApi.Api.Idempotency;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>
/// docs/architecture/API-SURFACE.md is normative: every endpoint the app serves is in it, and
/// each one's authorization and idempotency match its row.
/// </summary>
public class ApiSurfaceTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private sealed record Row(string Method, string Route, string Class, string Enforced, string Idempotency);

    private static IReadOnlyList<Row> Table()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "docs", "architecture", "API-SURFACE.md")))
        {
            directory = directory.Parent;
        }

        Assert.NotNull(directory);
        return File.ReadLines(Path.Combine(directory!.FullName, "docs", "architecture", "API-SURFACE.md"))
            .Where(line => line.StartsWith("| ", StringComparison.Ordinal) && line.Contains('`', StringComparison.Ordinal))
            .Select(line => line.Split('|', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries))
            .Select(cells => new Row(cells[0], cells[1].Trim('`'), cells[2], cells[3], cells[4]))
            .ToList();
    }

    private IReadOnlyList<(string Method, string Route, RouteEndpoint Endpoint)> Served() =>
        factory.Services.GetRequiredService<EndpointDataSource>().Endpoints
            .OfType<RouteEndpoint>()
            .SelectMany(e => (e.Metadata.GetMetadata<HttpMethodMetadata>()?.HttpMethods ?? ["ANY"])
                .Select(m => (m, "/" + e.RoutePattern.RawText!.Trim('/'), e)))
            .ToList();

    [Fact]
    public void Every_served_endpoint_is_classified_and_every_classified_endpoint_is_served()
    {
        var served = Served().Select(s => $"{s.Method} {s.Route}").ToHashSet();
        var listed = Table().Select(r => $"{r.Method} {r.Route}").ToHashSet();

        Assert.Empty(served.Except(listed)); // unclassified: add a row to API-SURFACE.md
        Assert.Empty(listed.Except(served)); // listed but gone: remove the row
    }

    [Fact]
    public void Each_endpoint_is_open_or_token_gated_as_its_row_says()
    {
        var served = Served().ToDictionary(s => $"{s.Method} {s.Route}", s => s.Endpoint);
        foreach (var row in Table())
        {
            var open = served[$"{row.Method} {row.Route}"].Metadata.GetMetadata<IAllowAnonymous>() is not null;
            Assert.True(open == (row.Enforced == "open"), $"{row.Method} {row.Route} should be {row.Enforced}");
        }
    }

    [Fact]
    public void Each_write_honours_an_idempotency_key_and_no_read_needs_one()
    {
        var served = Served().ToDictionary(s => $"{s.Method} {s.Route}", s => s.Endpoint);
        foreach (var row in Table())
        {
            var honoured = served[$"{row.Method} {row.Route}"].Metadata.GetMetadata<IdempotentWriteMetadata>() is not null;
            Assert.True(honoured == (row.Idempotency == "honoured"), $"{row.Method} {row.Route}: Idempotency-Key {row.Idempotency}");
            Assert.True(row.Class == "read" || honoured, $"{row.Method} {row.Route} is a {row.Class} and must honour Idempotency-Key");
            Assert.True(row.Class != "read" || row.Enforced == "open", $"{row.Method} {row.Route}: reads stay open");
        }
    }

    [Fact]
    public void The_table_only_uses_the_classes_it_defines()
    {
        string[] classes = ["read", "plan", "approval", "gated-write", "write", "safety-write"];

        Assert.All(Table(), row => Assert.Contains(row.Class, classes));
        Assert.Single(Table(), row => row.Class == "gated-write");
    }
}
