using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using SwarmApi.Api.Idempotency;
using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>
/// A client-supplied Idempotency-Key turns "did my write happen?" into a safe retry
/// (architecture-standards SERVICE-API-PATTERNS).
/// </summary>
public class IdempotencyTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private static CreateMissionRequest Request(string name = "Idempotent") => new(
        Name: name,
        Type: "waypoint",
        Waypoints: [new WaypointDto(0, 0, 5), new WaypointDto(10, 0, 5)],
        DroneCount: 2,
        SpacingMeters: 3.0);

    private static HttpRequestMessage Post(string path, object? body, string? key)
    {
        var message = new HttpRequestMessage(HttpMethod.Post, path) { Content = body is null ? null : JsonContent.Create(body) };
        if (key is not null)
        {
            message.Headers.Add(IdempotencyFilter.HeaderName, key);
        }

        return message;
    }

    [Fact]
    public async Task A_replayed_write_returns_the_original_answer_instead_of_running_again()
    {
        var client = factory.CreateClient();
        var key = Guid.NewGuid().ToString();

        var first = await client.SendAsync(Post("/api/missions", Request(), key));
        var replay = await client.SendAsync(Post("/api/missions", Request(), key));

        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        Assert.Equal(HttpStatusCode.Created, replay.StatusCode);
        var original = await first.Content.ReadFromJsonAsync<Mission>(TestJson.Options);
        var replayed = await replay.Content.ReadFromJsonAsync<Mission>(TestJson.Options);
        Assert.Equal(original!.Id, replayed!.Id);
        Assert.Equal(first.Headers.Location, replay.Headers.Location);
        Assert.False(first.Headers.Contains(IdempotencyFilter.ReplayedHeaderName));
        Assert.Equal("true", replay.Headers.GetValues(IdempotencyFilter.ReplayedHeaderName).Single());
        // Still the active mission: a second run would have superseded (aborted) it.
        var mission = await client.GetFromJsonAsync<Mission>($"/api/missions/{original.Id}", TestJson.Options);
        Assert.Equal(MissionStatus.Active, mission!.Status);
    }

    [Fact]
    public async Task The_same_key_for_a_different_request_is_refused()
    {
        var client = factory.CreateClient();
        var key = Guid.NewGuid().ToString();
        await client.SendAsync(Post("/api/missions", Request("one"), key));

        var reused = await client.SendAsync(Post("/api/missions", Request("two"), key));

        Assert.Equal(HttpStatusCode.UnprocessableEntity, reused.StatusCode);
    }

    [Fact]
    public async Task Keys_are_scoped_to_the_endpoint_and_malformed_keys_are_rejected()
    {
        var client = factory.CreateClient();
        var key = Guid.NewGuid().ToString();

        var mission = await client.SendAsync(Post("/api/missions", Request(), key));
        var plan = await client.SendAsync(Post("/api/mission-plans", Request(), key));
        var malformed = await client.SendAsync(Post("/api/missions", Request(), "has spaces in it"));

        Assert.Equal(HttpStatusCode.Created, mission.StatusCode);
        Assert.Equal(HttpStatusCode.Created, plan.StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, malformed.StatusCode);
    }

    [Fact]
    public async Task A_refused_answer_is_replayed_too_so_a_retry_cannot_turn_it_into_a_success()
    {
        var client = factory.CreateClient();
        var key = Guid.NewGuid().ToString();
        var invalid = Request() with { DroneCount = 99 };

        var first = await client.SendAsync(Post("/api/missions", invalid, key));
        var replay = await client.SendAsync(Post("/api/missions", invalid, key));

        Assert.Equal(HttpStatusCode.BadRequest, first.StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, replay.StatusCode);
        Assert.Equal(await first.Content.ReadAsStringAsync(), await replay.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task A_503_is_not_stored_so_a_retry_with_the_same_key_runs_again()
    {
        var bridge = new FlakyBridge();
        using var flaky = factory.WithWebHostBuilder(builder =>
            builder.ConfigureServices(services => services.AddSingleton<ISwarmBridge>(bridge)));
        var client = flaky.CreateClient();
        var key = Guid.NewGuid().ToString();

        var unreachable = await client.SendAsync(Post("/api/missions", Request(), key));
        bridge.Reachable = true;
        var retried = await client.SendAsync(Post("/api/missions", Request(), key));

        Assert.Equal(HttpStatusCode.ServiceUnavailable, unreachable.StatusCode);
        Assert.Equal(HttpStatusCode.Created, retried.StatusCode);
        Assert.False(retried.Headers.Contains(IdempotencyFilter.ReplayedHeaderName));
    }

    [Fact]
    public async Task Without_a_key_every_request_runs()
    {
        var client = factory.CreateClient();

        var first = await (await client.PostAsJsonAsync("/api/missions", Request())).Content.ReadFromJsonAsync<Mission>(TestJson.Options);
        var second = await (await client.PostAsJsonAsync("/api/missions", Request())).Content.ReadFromJsonAsync<Mission>(TestJson.Options);

        Assert.NotEqual(first!.Id, second!.Id);
    }

    private sealed class FlakyBridge : ISwarmBridge
    {
        private readonly SimulatedSwarmBridge _inner = new();

        public bool Reachable { get; set; }

        public SwarmBridgeMode Mode => Reachable ? SwarmBridgeMode.Connected : SwarmBridgeMode.Disconnected;

        public DateTimeOffset? LastStateReceivedUtc => null;

        public Task DispatchMissionAsync(Mission mission, CancellationToken cancellationToken = default) =>
            Reachable ? _inner.DispatchMissionAsync(mission, cancellationToken) : throw new SwarmUnavailableException("down");

        public Task SendCommandAsync(SwarmCommand command, Guid? missionId, CancellationToken cancellationToken = default) =>
            _inner.SendCommandAsync(command, missionId, cancellationToken);

        public Task<SwarmState> GetStateAsync(CancellationToken cancellationToken = default) =>
            _inner.GetStateAsync(cancellationToken);
    }
}
