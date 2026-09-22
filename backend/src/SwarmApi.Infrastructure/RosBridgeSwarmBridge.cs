using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;

namespace SwarmApi.Infrastructure;

/// <summary>
/// The real <see cref="ISwarmBridge"/>: a rosbridge_suite WebSocket connection that
/// publishes missions to <c>/swarm/mission</c> and commands to <c>/swarm/command</c>, and
/// keeps the latest <c>/swarm/state</c>. The ROS-side other half of the contract is
/// <c>swarm_coordination/nodes/mission_dispatcher_node.py</c> and
/// <c>swarm_state_aggregator_node.py</c>; the messages themselves are in
/// <c>contracts/rosbridge/</c> and encoded by <see cref="RosBridgeProtocol"/> (P11).
///
/// The connection is owned by <see cref="RunAsync"/>, which <see cref="RosBridgeConnectionService"/>
/// runs for the life of the process: it connects, reconnects with a doubling back-off
/// after any failure or drop, and <see cref="Mode"/> says which state it is in at the
/// moment it is read — so <c>/health</c> degrades when the swarm does, not only at startup.
/// </summary>
public sealed class RosBridgeSwarmBridge : ISwarmBridge, IAsyncDisposable
{
    /// <summary>Opens a WebSocket to <paramref name="uri"/>; injectable so tests can connect to an in-process server.</summary>
    public delegate Task<WebSocket> Connector(Uri uri, CancellationToken cancellationToken);

    private readonly Uri _uri;
    private readonly RosBridgeOptions _options;
    private readonly TimeProvider _time;
    private readonly ILogger _logger;
    private readonly Connector _connect;

    // ClientWebSocket allows one outstanding send at a time; requests arrive concurrently.
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private readonly object _stateLock = new();
    private WebSocket? _socket;
    private SwarmState? _lastState;
    private DateTimeOffset? _lastStateReceivedUtc;
    private long _malformedMessages;

    public RosBridgeSwarmBridge(
        Uri uri,
        RosBridgeOptions options,
        TimeProvider time,
        ILogger<RosBridgeSwarmBridge> logger,
        Connector? connector = null)
    {
        _uri = uri;
        _options = options;
        _time = time;
        _logger = logger;
        _connect = connector ?? ConnectClientWebSocketAsync;
    }

    public SwarmBridgeMode Mode =>
        Volatile.Read(ref _socket) is { State: WebSocketState.Open } ? SwarmBridgeMode.Connected : SwarmBridgeMode.Disconnected;

    public DateTimeOffset? LastStateReceivedUtc
    {
        get
        {
            lock (_stateLock)
            {
                return _lastStateReceivedUtc;
            }
        }
    }

    /// <summary>How many messages were dropped as malformed or oversized since startup.</summary>
    public long MalformedMessageCount => Interlocked.Read(ref _malformedMessages);

    /// <summary>
    /// Keeps a connection open until <paramref name="stoppingToken"/> fires: connect,
    /// advertise the topics this client publishes, subscribe to state, receive until the
    /// connection ends, then wait and try again. Never throws for a connection problem.
    /// </summary>
    public async Task RunAsync(CancellationToken stoppingToken)
    {
        var initialDelay = TimeSpan.FromSeconds(_options.ReconnectInitialDelaySeconds);
        var maxDelay = TimeSpan.FromSeconds(Math.Max(_options.ReconnectMaxDelaySeconds, _options.ReconnectInitialDelaySeconds));
        var delay = initialDelay;

        while (!stoppingToken.IsCancellationRequested)
        {
            WebSocket? socket = null;
            try
            {
                using (var attempt = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken))
                {
                    attempt.CancelAfter(TimeSpan.FromSeconds(_options.ConnectTimeoutSeconds));
                    socket = await _connect(_uri, attempt.Token);
                    await SendRawAsync(socket, RosBridgeProtocol.Advertise(RosBridgeProtocol.MissionTopic), attempt.Token);
                    await SendRawAsync(socket, RosBridgeProtocol.Advertise(RosBridgeProtocol.CommandTopic), attempt.Token);
                    await SendRawAsync(socket, RosBridgeProtocol.Subscribe(RosBridgeProtocol.StateTopic), attempt.Token);
                }

                Volatile.Write(ref _socket, socket);
                delay = initialDelay;
                _logger.LogInformation("RosBridge connected to {Url}; the swarm is reachable.", _uri);

                await ReceiveLoopAsync(socket, stoppingToken);
                if (!stoppingToken.IsCancellationRequested)
                {
                    _logger.LogWarning("RosBridge connection to {Url} closed; reconnecting.", _uri);
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogWarning(
                    "RosBridge at {Url} unreachable ({Reason}); retrying in {DelaySeconds:0.#}s.",
                    _uri, ex.Message, delay.TotalSeconds);
            }
            finally
            {
                await ReleaseSocketAsync(socket);
            }

            try
            {
                await Task.Delay(delay, _time, stoppingToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }

            delay = TimeSpan.FromTicks(Math.Min(delay.Ticks * 2, maxDelay.Ticks));
        }
    }

    public Task DispatchMissionAsync(Mission mission, CancellationToken cancellationToken = default) =>
        PublishAsync(RosBridgeProtocol.MissionTopic, RosBridgeProtocol.MissionPayload(mission), cancellationToken);

    public Task SendCommandAsync(SwarmCommand command, Guid? missionId, CancellationToken cancellationToken = default) =>
        PublishAsync(RosBridgeProtocol.CommandTopic, RosBridgeProtocol.CommandPayload(command, missionId), cancellationToken);

    public Task<SwarmState> GetStateAsync(CancellationToken cancellationToken = default)
    {
        var mode = Mode;
        lock (_stateLock)
        {
            // The last state received, however old, with the live mode stamped on it:
            // stale positions are still the best available, but never labelled Connected
            // once the connection they came from is gone. Each drone's LastUpdatedUtc and
            // /health's lastStateAgeSeconds say how old they are.
            return Task.FromResult(new SwarmState
            {
                Drones = _lastState?.Drones ?? [],
                ActiveMissionId = _lastState?.ActiveMissionId,
                ActiveMissionComplete = _lastState?.ActiveMissionComplete ?? false,
                TimestampUtc = _lastStateReceivedUtc ?? _time.GetUtcNow(),
                BridgeMode = mode,
            });
        }
    }

    public async ValueTask DisposeAsync()
    {
        await ReleaseSocketAsync(Volatile.Read(ref _socket));
        _sendLock.Dispose();
    }

    private async Task PublishAsync(string topic, string payload, CancellationToken cancellationToken)
    {
        await _sendLock.WaitAsync(cancellationToken);
        try
        {
            var socket = Volatile.Read(ref _socket);
            if (socket is not { State: WebSocketState.Open })
            {
                throw new SwarmUnavailableException(
                    $"The swarm is not reachable: rosbridge at {_uri} is disconnected and being retried.");
            }

            await SendRawAsync(socket, RosBridgeProtocol.Publish(topic, payload), cancellationToken);
        }
        catch (Exception ex) when (ex is WebSocketException or ObjectDisposedException or IOException)
        {
            // Indeterminate: part of the message may have left. Reported as unavailable so a
            // caller does not assume the mission is flying — and must not blindly resend it.
            throw new SwarmUnavailableException($"Sending to rosbridge at {_uri} failed: {ex.Message}", ex);
        }
        finally
        {
            _sendLock.Release();
        }
    }

    private static Task SendRawAsync(WebSocket socket, string json, CancellationToken cancellationToken) =>
        socket.SendAsync(new ArraySegment<byte>(Encoding.UTF8.GetBytes(json)), WebSocketMessageType.Text, endOfMessage: true, cancellationToken);

    private async Task ReceiveLoopAsync(WebSocket socket, CancellationToken cancellationToken)
    {
        var buffer = new byte[16 * 1024];
        using var message = new MemoryStream();

        while (socket.State == WebSocketState.Open && !cancellationToken.IsCancellationRequested)
        {
            message.SetLength(0);
            var oversized = false;
            ValueWebSocketReceiveResult result;
            do
            {
                result = await socket.ReceiveAsync(buffer.AsMemory(), cancellationToken);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    return;
                }

                if (message.Length + result.Count > _options.MaxMessageBytes)
                {
                    oversized = true;
                }
                else
                {
                    message.Write(buffer, 0, result.Count);
                }
            }
            while (!result.EndOfMessage);

            if (oversized)
            {
                CountMalformed($"a message larger than {_options.MaxMessageBytes} bytes", null);
                continue;
            }

            HandleMessage(Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length));
        }
    }

    private void HandleMessage(string text)
    {
        try
        {
            if (!RosBridgeProtocol.TryReadStateEnvelope(text, out var stateJson))
            {
                return;
            }

            var now = _time.GetUtcNow();
            var state = RosBridgeProtocol.ParseState(stateJson, now);
            lock (_stateLock)
            {
                _lastState = state;
                _lastStateReceivedUtc = now;
            }
        }
        catch (Exception ex) when (ex is JsonException or FormatException)
        {
            // One bad message must not end the loop: before, it faulted the receive task
            // silently and froze the state while /health still said Connected.
            CountMalformed("a malformed message", ex);
        }
    }

    private void CountMalformed(string what, Exception? ex)
    {
        var count = Interlocked.Increment(ref _malformedMessages);
        if (count == 1 || count % 100 == 0)
        {
            _logger.LogWarning(ex, "RosBridge dropped {What} ({Count} dropped so far).", what, count);
        }
    }

    private async Task ReleaseSocketAsync(WebSocket? socket)
    {
        if (socket is null)
        {
            return;
        }

        // Taking the send lock means no publish is mid-flight on the socket being disposed.
        await _sendLock.WaitAsync();
        try
        {
            Interlocked.CompareExchange(ref _socket, null, socket);
            if (socket.State == WebSocketState.Open)
            {
                using var closeTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                try
                {
                    await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "reconnecting", closeTimeout.Token);
                }
#pragma warning disable CA1031 // Best effort by design: this runs in RunAsync's finally, and anything
                // escaping it would end the background service — and with it the host.
                catch (Exception)
#pragma warning restore CA1031
                {
                    // the peer may already be gone; the socket is disposed below either way
                }
            }

            socket.Dispose();
        }
        finally
        {
            _sendLock.Release();
        }
    }

    private static async Task<WebSocket> ConnectClientWebSocketAsync(Uri uri, CancellationToken cancellationToken)
    {
        var socket = new ClientWebSocket();
        try
        {
            await socket.ConnectAsync(uri, cancellationToken);
            return socket;
        }
        catch
        {
            socket.Dispose();
            throw;
        }
    }
}
