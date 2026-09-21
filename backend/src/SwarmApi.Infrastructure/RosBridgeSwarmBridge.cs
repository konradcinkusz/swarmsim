using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;

namespace SwarmApi.Infrastructure;

/// <summary>
/// The real <see cref="ISwarmBridge"/>: a persistent rosbridge_suite WebSocket
/// connection. Publishes dispatched missions to <c>/swarm/mission</c> and maintains
/// the latest <c>/swarm/state</c> message from a background receive loop — see
/// <c>swarm_coordination/nodes/mission_dispatcher_node.py</c> and
/// <c>swarm_state_aggregator_node.py</c> for the ROS-side other half of this contract.
///
/// The JSON dialect on the wire is normalized into the internal <c>SwarmApi.Domain</c>
/// model right here, once (P11) — nothing above <see cref="ISwarmBridge"/> knows a
/// rosbridge message was ever involved.
/// </summary>
public sealed class RosBridgeSwarmBridge : ISwarmBridge, IAsyncDisposable
{
    private readonly Uri _uri;
    private readonly ClientWebSocket _socket;
    private readonly Dictionary<Guid, Mission> _missions = new();
    private readonly object _stateLock = new();
    private readonly object _missionsLock = new();
    private SwarmState _lastState;
    private CancellationTokenSource? _receiveLoopCts;
    private Task? _receiveLoopTask;

    public RosBridgeSwarmBridge(Uri uri, ClientWebSocket socket)
    {
        _uri = uri;
        _socket = socket;
        _lastState = new SwarmState
        {
            Drones = [],
            ActiveMissionId = null,
            TimestampUtc = DateTimeOffset.UtcNow,
            BridgeMode = SwarmBridgeMode.Connected,
        };
    }

    public SwarmBridgeMode Mode => SwarmBridgeMode.Connected;

    /// <summary>
    /// Subscribes to <c>/swarm/state</c> and starts the background receive loop.
    /// The socket must already be open — <see cref="ServiceCollectionExtensions.AddSwarmBridgeAsync"/>
    /// owns the initial <c>ConnectAsync</c>, so a failed connection never leaves a bridge half-started.
    /// </summary>
    public Task StartAsync(CancellationToken cancellationToken)
    {
        _receiveLoopCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        _receiveLoopTask = Task.Run(() => ReceiveLoopAsync(_receiveLoopCts.Token), CancellationToken.None);
        return SendAsync(RosBridgeProtocol.Subscribe("/swarm/state"), cancellationToken);
    }

    public async Task<Mission> DispatchMissionAsync(
        CreateMissionRequest request, CancellationToken cancellationToken = default)
    {
        var mission = new Mission
        {
            Id = Guid.NewGuid(),
            Name = request.Name,
            Type = request.Type == "formation" ? MissionType.LeaderFollowerFormation : MissionType.WaypointFollow,
            Waypoints = request.Waypoints.Select(w => new Vector3(w.X, w.Y, w.Z)).ToList(),
            DroneCount = request.DroneCount,
            SpacingMeters = request.SpacingMeters,
            CreatedAtUtc = DateTimeOffset.UtcNow,
        };

        lock (_missionsLock)
        {
            _missions[mission.Id] = mission;
        }

        var payload = JsonSerializer.Serialize(new
        {
            mission_id = mission.Id,
            type = request.Type,
            waypoints = request.Waypoints.Select(w => new[] { w.X, w.Y, w.Z }),
            drone_count = request.DroneCount,
            spacing_m = request.SpacingMeters,
        });

        await SendAsync(RosBridgeProtocol.Publish("/swarm/mission", payload), cancellationToken);
        return mission;
    }

    public Task<SwarmState> GetStateAsync(CancellationToken cancellationToken = default)
    {
        lock (_stateLock)
        {
            return Task.FromResult(_lastState);
        }
    }

    public Task<Mission?> GetMissionAsync(Guid missionId, CancellationToken cancellationToken = default)
    {
        lock (_missionsLock)
        {
            return Task.FromResult(_missions.GetValueOrDefault(missionId));
        }
    }

    private async Task SendAsync(string json, CancellationToken cancellationToken)
    {
        var bytes = Encoding.UTF8.GetBytes(json);
        await _socket.SendAsync(
            new ArraySegment<byte>(bytes), WebSocketMessageType.Text, endOfMessage: true, cancellationToken);
    }

    private async Task ReceiveLoopAsync(CancellationToken cancellationToken)
    {
        var buffer = new ArraySegment<byte>(new byte[16 * 1024]);
        while (!cancellationToken.IsCancellationRequested && _socket.State == WebSocketState.Open)
        {
            try
            {
                using var messageStream = new MemoryStream();
                WebSocketReceiveResult result;
                do
                {
                    result = await _socket.ReceiveAsync(buffer, cancellationToken);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        return;
                    }

                    messageStream.Write(buffer.Array!, buffer.Offset, result.Count);
                }
                while (!result.EndOfMessage);

                messageStream.Position = 0;
                HandleIncomingMessage(messageStream);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (WebSocketException)
            {
                // The connection dropped after startup: GetStateAsync keeps serving the
                // last known state (stale, not wrong) rather than throwing into a
                // request handler. Reconnection is a documented follow-up — see
                // docs/architecture/DEVIATIONS.md.
                return;
            }
        }
    }

    private void HandleIncomingMessage(Stream messageStream)
    {
        using var document = JsonDocument.Parse(messageStream);
        var root = document.RootElement;
        if (!root.TryGetProperty("topic", out var topicElement) || topicElement.GetString() != "/swarm/state")
        {
            return;
        }

        if (!root.TryGetProperty("msg", out var msgElement) || !msgElement.TryGetProperty("data", out var dataElement))
        {
            return;
        }

        var stateJson = dataElement.GetString();
        if (string.IsNullOrEmpty(stateJson))
        {
            return;
        }

        var state = ParseSwarmState(stateJson);
        lock (_stateLock)
        {
            _lastState = state;
        }
    }

    private static SwarmState ParseSwarmState(string json)
    {
        using var document = JsonDocument.Parse(json);
        var drones = new List<DroneState>();
        var now = DateTimeOffset.UtcNow;

        if (document.RootElement.TryGetProperty("drones", out var dronesElement))
        {
            foreach (var d in dronesElement.EnumerateArray())
            {
                drones.Add(new DroneState
                {
                    Id = d.GetProperty("id").GetString() ?? "unknown",
                    Position = new Vector3(
                        d.GetProperty("x").GetDouble(),
                        d.GetProperty("y").GetDouble(),
                        d.GetProperty("z").GetDouble()),
                    Status = DroneStatus.InFlight,
                    LastUpdatedUtc = now,
                });
            }
        }

        return new SwarmState
        {
            Drones = drones,
            ActiveMissionId = null,
            TimestampUtc = now,
            BridgeMode = SwarmBridgeMode.Connected,
        };
    }

    public async ValueTask DisposeAsync()
    {
        _receiveLoopCts?.Cancel();
        if (_receiveLoopTask is not null)
        {
            try
            {
                await _receiveLoopTask;
            }
            catch (OperationCanceledException)
            {
                // expected on shutdown
            }
        }

        if (_socket.State == WebSocketState.Open)
        {
            try
            {
                await _socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "shutting down", CancellationToken.None);
            }
            catch (WebSocketException)
            {
                // best-effort close
            }
        }

        _socket.Dispose();
        _receiveLoopCts?.Dispose();
    }
}

internal static class RosBridgeProtocol
{
    public static string Subscribe(string topic) =>
        JsonSerializer.Serialize(new { op = "subscribe", topic, type = "std_msgs/String" });

    public static string Publish(string topic, string dataJson) =>
        JsonSerializer.Serialize(new { op = "publish", topic, msg = new { data = dataJson } });
}
