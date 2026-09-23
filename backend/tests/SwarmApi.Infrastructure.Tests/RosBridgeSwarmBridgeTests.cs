using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;
using Xunit;

namespace SwarmApi.Infrastructure.Tests;

/// <summary>
/// The connection behaviour P8 asks for once startup is over: a dropped or refused
/// rosbridge is visible in <see cref="RosBridgeSwarmBridge.Mode"/>, retried, and survived;
/// bad messages are dropped without ending the connection; concurrent requests do not
/// collide on the one socket.
/// </summary>
public sealed class RosBridgeSwarmBridgeTests : IAsyncLifetime
{
    private static readonly Uri RosBridgeUri = new("ws://localhost/");
    private FakeRosBridge _server = null!;
    private RosBridgeSwarmBridge _bridge = null!;
    private CancellationTokenSource _stop = null!;
    private Task _run = Task.CompletedTask;

    public async Task InitializeAsync()
    {
        _server = await FakeRosBridge.StartAsync();
        _stop = new CancellationTokenSource();
    }

    public async Task DisposeAsync()
    {
        _stop.Cancel();
        await _run;
        await _bridge.DisposeAsync();
        await _server.DisposeAsync();
        _stop.Dispose();
    }

    private void StartBridge(int maxMessageBytes = 1024 * 1024)
    {
        var options = new RosBridgeOptions
        {
            ConnectTimeoutSeconds = 2,
            ReconnectInitialDelaySeconds = 0.05,
            ReconnectMaxDelaySeconds = 0.2,
            MaxMessageBytes = maxMessageBytes,
        };
        _bridge = new RosBridgeSwarmBridge(
            RosBridgeUri, options, TimeProvider.System, NullLogger<RosBridgeSwarmBridge>.Instance, _server.Connector);
        _run = _bridge.RunAsync(_stop.Token);
    }

    private static async Task Eventually(Func<bool> condition, string what)
    {
        var deadline = DateTime.UtcNow.AddSeconds(10);
        while (!condition())
        {
            if (DateTime.UtcNow > deadline)
            {
                throw new TimeoutException($"timed out waiting for: {what}");
            }

            await Task.Delay(20);
        }
    }

    private static string StateMessage(double x) => RosBridgeProtocol.Publish(
        RosBridgeProtocol.StateTopic,
        $$"""{"version":1,"frame":"world_enu","drones":[{"id":"drone_1","x":{{x}},"y":0,"z":5,"armed":true,"mode":"OFFBOARD"}]}""");

    private static Mission AMission() => new()
    {
        Id = Guid.NewGuid(),
        Name = "probe",
        Type = MissionType.WaypointFollow,
        Waypoints = [new Vector3(0, 0, 5)],
        DroneCount = 1,
        CreatedAtUtc = DateTimeOffset.UtcNow,
    };

    [Fact]
    public async Task Connecting_advertises_both_outgoing_topics_and_subscribes_to_state()
    {
        StartBridge();

        await Eventually(() => _bridge.Mode == SwarmBridgeMode.Connected, "connected");
        await Eventually(() => _server.Received.Count >= 3, "three setup messages");

        var setup = _server.Received.Take(3).ToList();
        Assert.Contains(setup, m => m.Contains("\"op\":\"advertise\"") && m.Contains("/swarm/mission"));
        Assert.Contains(setup, m => m.Contains("\"op\":\"advertise\"") && m.Contains("/swarm/command"));
        Assert.Contains(setup, m => m.Contains("\"op\":\"subscribe\"") && m.Contains("/swarm/state"));
    }

    [Fact]
    public async Task A_malformed_message_is_dropped_and_the_next_state_still_arrives()
    {
        StartBridge();
        await Eventually(() => _bridge.Mode == SwarmBridgeMode.Connected, "connected");

        await _server.SendAsync("{this is not json");
        await _server.SendAsync(RosBridgeProtocol.Publish(RosBridgeProtocol.StateTopic, """{"drones":[{"id":"drone_1"}]}"""));
        await _server.SendFragmentedAsync(StateMessage(x: 7.5), fragments: 4);

        await Eventually(() => _bridge.GetStateAsync().Result.Drones.Count == 1, "state after the bad messages");
        var state = await _bridge.GetStateAsync();
        Assert.Equal(7.5, state.Drones[0].Position.X);
        Assert.Equal(2, _bridge.MalformedMessageCount);
        Assert.Equal(SwarmBridgeMode.Connected, _bridge.Mode);
        Assert.NotNull(_bridge.LastStateReceivedUtc);
    }

    [Fact]
    public async Task An_oversized_message_is_dropped_without_ending_the_connection()
    {
        StartBridge(maxMessageBytes: 512);
        await Eventually(() => _bridge.Mode == SwarmBridgeMode.Connected, "connected");

        await _server.SendFragmentedAsync(new string(' ', 2000) + StateMessage(x: 1), fragments: 5);
        await _server.SendAsync(StateMessage(x: 2));

        await Eventually(() => _bridge.GetStateAsync().Result.Drones.Count == 1, "state after the oversized message");
        Assert.Equal(2, (await _bridge.GetStateAsync()).Drones[0].Position.X);
        Assert.Equal(1, _bridge.MalformedMessageCount);
    }

    [Fact]
    public async Task Concurrent_dispatches_are_all_delivered_one_frame_each()
    {
        StartBridge();
        await Eventually(() => _bridge.Mode == SwarmBridgeMode.Connected, "connected");

        await Task.WhenAll(Enumerable.Range(0, 25).Select(_ => _bridge.DispatchMissionAsync(AMission())));

        // Publishes are counted, not frames: the bridge sends its advertise and subscribe
        // frames before it reads as Connected, but the server can record them after this
        // test has, and counting frames from that moment on failed 3 runs in 40.
        await Eventually(() => Publishes().Count >= 25, "25 missions received");
        Assert.Equal(25, Publishes().Count);
        Assert.All(Publishes(), m => Assert.Contains("\"topic\":\"/swarm/mission\"", m));
        Assert.All(_server.Received, frame => JsonDocument.Parse(frame).Dispose());

        List<string> Publishes() => _server.Received.Where(m => m.Contains("\"op\":\"publish\"")).ToList();
    }

    [Fact]
    public async Task A_dropped_connection_reads_as_disconnected_until_rosbridge_is_back()
    {
        StartBridge();
        await Eventually(() => _bridge.Mode == SwarmBridgeMode.Connected, "first connection");
        await _server.SendAsync(StateMessage(x: 3));
        await Eventually(() => _bridge.GetStateAsync().Result.Drones.Count == 1, "first state");

        _server.AcceptConnections = false;
        _server.DropConnection();

        await Eventually(() => _bridge.Mode == SwarmBridgeMode.Disconnected, "disconnected");
        await Assert.ThrowsAsync<SwarmUnavailableException>(() => _bridge.DispatchMissionAsync(AMission()));
        var stale = await _bridge.GetStateAsync();
        Assert.Equal(SwarmBridgeMode.Disconnected, stale.BridgeMode);
        Assert.Single(stale.Drones); // the last known positions stay readable, labelled as not live

        _server.AcceptConnections = true;
        await Eventually(() => _bridge.Mode == SwarmBridgeMode.Connected, "reconnected");
        Assert.True(_server.ConnectionCount >= 2);
        await _bridge.DispatchMissionAsync(AMission());
    }

    [Fact]
    public async Task A_rosbridge_that_is_down_at_startup_is_retried_rather_than_replaced()
    {
        _server.AcceptConnections = false;
        StartBridge();

        await Task.Delay(300);
        Assert.Equal(SwarmBridgeMode.Disconnected, _bridge.Mode);

        _server.AcceptConnections = true;
        await Eventually(() => _bridge.Mode == SwarmBridgeMode.Connected, "connected once rosbridge is up");
    }
}
