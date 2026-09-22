using System.Globalization;
using System.Text.Json;
using SwarmApi.Domain;

namespace SwarmApi.Infrastructure;

/// <summary>
/// The rosbridge dialect, translated in one place (P11) and kept free of I/O so it can be
/// tested against the shared contract files in <c>contracts/rosbridge/</c> — the same files
/// the Python side is tested against. <see cref="RosBridgeSwarmBridge"/> only moves the
/// strings this class produces and consumes.
/// </summary>
public static class RosBridgeProtocol
{
    public const string MissionTopic = "/swarm/mission";
    public const string CommandTopic = "/swarm/command";
    public const string StateTopic = "/swarm/state";
    public const string StringMessageType = "std_msgs/String";
    public const int ContractVersion = 1;

    public static string Subscribe(string topic) =>
        JsonSerializer.Serialize(new { op = "subscribe", topic, type = StringMessageType });

    /// <summary>
    /// Declares a topic this client publishes on. rosbridge cannot infer the type of a topic
    /// nobody has created yet, so publishing without advertising first fails whenever the
    /// ROS side has not subscribed — and fails silently, as a status message nobody reads.
    /// </summary>
    public static string Advertise(string topic) =>
        JsonSerializer.Serialize(new { op = "advertise", topic, type = StringMessageType });

    public static string Publish(string topic, string dataJson) =>
        JsonSerializer.Serialize(new { op = "publish", topic, msg = new { data = dataJson } });

    /// <summary>The <c>/swarm/mission</c> payload (contracts/rosbridge/swarm_mission.v1.schema.json).</summary>
    public static string MissionPayload(Mission mission) =>
        JsonSerializer.Serialize(new
        {
            version = ContractVersion,
            mission_id = mission.Id,
            type = mission.Type == MissionType.LeaderFollowerFormation ? "formation" : "waypoint",
            formation = mission.Formation == FormationShape.V ? "v" : "line",
            waypoints = mission.Waypoints.Select(w => new[] { w.X, w.Y, w.Z }),
            drone_count = mission.DroneCount,
            spacing_m = mission.SpacingMeters,
        });

    /// <summary>The <c>/swarm/command</c> payload (contracts/rosbridge/swarm_command.v1.schema.json).</summary>
    public static string CommandPayload(SwarmCommand command, Guid? missionId) =>
        JsonSerializer.Serialize(new
        {
            version = ContractVersion,
            command = command switch
            {
                SwarmCommand.ReturnToLaunch => "rtl",
                SwarmCommand.Land => "land",
                SwarmCommand.Hold => "hold",
                _ => throw new ArgumentOutOfRangeException(nameof(command), command, "Unknown swarm command."),
            },
            mission_id = missionId,
        });

    /// <summary>
    /// Extracts the state JSON from a rosbridge message if it is a <c>/swarm/state</c>
    /// publication; false for anything else (status messages, other topics).
    /// </summary>
    public static bool TryReadStateEnvelope(string rosbridgeMessage, out string stateJson)
    {
        stateJson = string.Empty;
        using var document = JsonDocument.Parse(rosbridgeMessage);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object
            || !root.TryGetProperty("topic", out var topic)
            || topic.GetString() != StateTopic
            || !root.TryGetProperty("msg", out var msg)
            || !msg.TryGetProperty("data", out var data)
            || data.ValueKind != JsonValueKind.String)
        {
            return false;
        }

        stateJson = data.GetString() ?? string.Empty;
        return stateJson.Length > 0;
    }

    /// <summary>
    /// Parses a <c>/swarm/state</c> payload (contracts/rosbridge/swarm_state.v1.schema.json)
    /// into the domain model. The pre-contract shape (no <c>version</c>, drones with only
    /// id/x/y/z) is still accepted, with every unreported field left unknown. Throws
    /// <see cref="FormatException"/> for a payload that is neither.
    /// </summary>
    public static SwarmState ParseState(string stateJson, DateTimeOffset now)
    {
        try
        {
            using var document = JsonDocument.Parse(stateJson);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                throw new FormatException("swarm state must be a JSON object");
            }

            if (root.TryGetProperty("frame", out var frame) && frame.GetString() != "world_enu")
            {
                throw new FormatException($"unsupported swarm state frame '{frame.GetString()}'");
            }

            var drones = new List<DroneState>();
            if (root.TryGetProperty("drones", out var dronesElement))
            {
                foreach (var d in dronesElement.EnumerateArray())
                {
                    drones.Add(ParseDrone(d, now));
                }
            }

            Guid? missionId = null;
            var complete = false;
            if (root.TryGetProperty("mission", out var mission) && mission.ValueKind == JsonValueKind.Object)
            {
                missionId = Guid.Parse(mission.GetProperty("id").GetString() ?? string.Empty, CultureInfo.InvariantCulture);
                complete = mission.GetProperty("complete").GetBoolean();
            }

            return new SwarmState
            {
                Drones = drones,
                ActiveMissionId = missionId,
                ActiveMissionComplete = complete,
                TimestampUtc = now,
                BridgeMode = SwarmBridgeMode.Connected,
            };
        }
        catch (Exception ex) when (ex is JsonException or KeyNotFoundException or InvalidOperationException or ArgumentException)
        {
            throw new FormatException($"malformed swarm state: {ex.Message}", ex);
        }
    }

    /// <summary>
    /// Maps PX4's armed flag and flight mode (as MAVROS reports them) to a drone status.
    /// Nothing known means <see cref="DroneStatus.Unknown"/>, not a guess.
    /// </summary>
    public static DroneStatus StatusFromPx4(bool? armed, string? mode) => (armed, mode) switch
    {
        (null, _) => DroneStatus.Unknown,
        (false, _) => DroneStatus.Landed,
        (true, "AUTO.TAKEOFF") => DroneStatus.TakingOff,
        (true, "AUTO.LAND") => DroneStatus.Landing,
        (true, "AUTO.RTL") => DroneStatus.Returning,
        (true, "AUTO.LOITER") => DroneStatus.Holding,
        (true, _) => DroneStatus.InFlight,
    };

    private static DroneState ParseDrone(JsonElement d, DateTimeOffset now)
    {
        var armed = OptionalBool(d, "armed");
        var mode = OptionalString(d, "mode");
        var age = OptionalDouble(d, "age_s");

        return new DroneState
        {
            Id = d.GetProperty("id").GetString() ?? throw new FormatException("drone id must be a string"),
            Position = new Vector3(d.GetProperty("x").GetDouble(), d.GetProperty("y").GetDouble(), d.GetProperty("z").GetDouble()),
            Armed = armed,
            FlightMode = mode,
            Status = StatusFromPx4(armed, mode),
            BatteryPercent = OptionalDouble(d, "battery_pct"),
            CurrentWaypointIndex = OptionalInt(d, "waypoint_index") ?? 0,
            LastUpdatedUtc = age is { } seconds ? now - TimeSpan.FromSeconds(seconds) : now,
        };
    }

    private static bool? OptionalBool(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind is JsonValueKind.True or JsonValueKind.False ? v.GetBoolean() : null;

    private static string? OptionalString(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    private static double? OptionalDouble(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null;

    private static int? OptionalInt(JsonElement e, string name) =>
        e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetInt32() : null;
}
