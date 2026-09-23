using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Hosting;

namespace SwarmApi.Infrastructure.Tests;

/// <summary>
/// An in-process stand-in for rosbridge_suite: accepts WebSocket connections, records every
/// message a client sends, lets a test push messages to the connected client, drop the
/// connection, and refuse new ones — the failure modes the real bridge has to survive.
/// </summary>
internal sealed class FakeRosBridge : IAsyncDisposable
{
    private readonly IHost _host;
    private readonly ConcurrentQueue<string> _received = new();
    private volatile WebSocket? _current;
    private TaskCompletionSource _dropCurrent = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private int _connections;

    private FakeRosBridge(IHost host) => _host = host;

    /// <summary>When false, new connection attempts are refused with 503 (the swarm is down).</summary>
    public volatile bool AcceptConnections = true;

    public int ConnectionCount => Volatile.Read(ref _connections);

    public IReadOnlyCollection<string> Received => _received;

    public static async Task<FakeRosBridge> StartAsync()
    {
        FakeRosBridge? fake = null;
        var host = new HostBuilder()
            .ConfigureWebHost(web => web
                .UseTestServer()
                .Configure(app =>
                {
                    app.UseWebSockets();
                    app.Run(context => fake!.HandleAsync(context));
                }))
            .Build();
        fake = new FakeRosBridge(host);
        await host.StartAsync();
        return fake;
    }

    public RosBridgeSwarmBridge.Connector Connector => async (uri, ct) =>
        await _host.GetTestServer().CreateWebSocketClient().ConnectAsync(uri, ct);

    public async Task SendAsync(string message)
    {
        var socket = _current ?? throw new InvalidOperationException("no client connected");
        await socket.SendAsync(Encoding.UTF8.GetBytes(message), WebSocketMessageType.Text, true, CancellationToken.None);
    }

    /// <summary>Sends one message split across several frames, as a large rosbridge publish arrives.</summary>
    public async Task SendFragmentedAsync(string message, int fragments)
    {
        var socket = _current ?? throw new InvalidOperationException("no client connected");
        var bytes = Encoding.UTF8.GetBytes(message);
        var size = (int)Math.Ceiling(bytes.Length / (double)fragments);
        for (var offset = 0; offset < bytes.Length; offset += size)
        {
            var count = Math.Min(size, bytes.Length - offset);
            await socket.SendAsync(new ArraySegment<byte>(bytes, offset, count), WebSocketMessageType.Text,
                endOfMessage: offset + count >= bytes.Length, CancellationToken.None);
        }
    }

    /// <summary>Closes the current connection from the server side, as a restarting rosbridge would.</summary>
    public void DropConnection() => _dropCurrent.TrySetResult();

    public async ValueTask DisposeAsync()
    {
        DropConnection();
        await _host.StopAsync();
        _host.Dispose();
    }

    private async Task HandleAsync(HttpContext context)
    {
        if (!context.WebSockets.IsWebSocketRequest || !AcceptConnections)
        {
            context.Response.StatusCode = StatusCodes.Status503ServiceUnavailable;
            return;
        }

        using var socket = await context.WebSockets.AcceptWebSocketAsync();
        _dropCurrent = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var drop = _dropCurrent.Task;
        _current = socket;
        Interlocked.Increment(ref _connections);

        var buffer = new byte[64 * 1024];
        var receive = Task.Run(async () =>
        {
            try
            {
                // One entry per message, as rosbridge reads them: a frame can arrive in parts.
                using var message = new MemoryStream();
                while (socket.State == WebSocketState.Open)
                {
                    var result = await socket.ReceiveAsync(buffer, CancellationToken.None);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        return;
                    }

                    message.Write(buffer, 0, result.Count);
                    if (result.EndOfMessage)
                    {
                        _received.Enqueue(Encoding.UTF8.GetString(message.ToArray()));
                        message.SetLength(0);
                    }
                }
            }
            catch (Exception ex) when (ex is WebSocketException or OperationCanceledException or ObjectDisposedException)
            {
                // the client went away
            }
        });

        await Task.WhenAny(receive, drop);
        _current = null;
        if (socket.State == WebSocketState.Open)
        {
            try
            {
                await socket.CloseOutputAsync(WebSocketCloseStatus.EndpointUnavailable, "dropped", CancellationToken.None);
            }
            catch (Exception ex) when (ex is WebSocketException or ObjectDisposedException)
            {
                // already gone
            }
        }
    }
}
