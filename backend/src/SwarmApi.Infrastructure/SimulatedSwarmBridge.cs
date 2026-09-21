using SwarmApi.Application;
using SwarmApi.Application.Contracts;
using SwarmApi.Domain;

namespace SwarmApi.Infrastructure;

/// <summary>
/// The zero-dependency <see cref="ISwarmBridge"/> fallback (P8): a deterministic
/// in-memory swarm that advances towards each mission's waypoints by elapsed wall-clock
/// time. Registered whenever <c>RosBridge:Url</c> is unset or unreachable at startup —
/// see docs/adr/0003-rosbridge-degrade-pattern.md — and used directly by
/// <c>SwarmApi.Api.Tests</c>, which is what makes M3's acceptance criteria checkable
/// in CI with no container and no GPU.
/// </summary>
public sealed class SimulatedSwarmBridge : ISwarmBridge
{
    private const double SpeedMetersPerSecond = 2.0;
    private const double ArrivalToleranceMeters = 0.3;

    private readonly object _lock = new();
    private readonly Dictionary<Guid, Mission> _missions = new();
    private readonly TimeProvider _timeProvider;
    private List<SimulatedDrone> _drones = [];
    private IReadOnlyList<Vector3> _followerOffsets = [];
    private Guid? _activeMissionId;
    private DateTimeOffset _lastTickUtc;

    public SimulatedSwarmBridge(TimeProvider? timeProvider = null)
    {
        _timeProvider = timeProvider ?? TimeProvider.System;
        _lastTickUtc = _timeProvider.GetUtcNow();
    }

    public SwarmBridgeMode Mode => SwarmBridgeMode.Simulated;

    public Task<Mission> DispatchMissionAsync(
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
            CreatedAtUtc = _timeProvider.GetUtcNow(),
        };

        lock (_lock)
        {
            _missions[mission.Id] = mission;
            _activeMissionId = mission.Id;
            _drones = BuildSwarm(mission);
            _lastTickUtc = _timeProvider.GetUtcNow();
        }

        return Task.FromResult(mission);
    }

    public Task<SwarmState> GetStateAsync(CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            Advance();
            return Task.FromResult(new SwarmState
            {
                Drones = _drones.Select(d => d.ToDroneState()).ToList(),
                ActiveMissionId = _activeMissionId,
                TimestampUtc = _timeProvider.GetUtcNow(),
                BridgeMode = SwarmBridgeMode.Simulated,
            });
        }
    }

    public Task<Mission?> GetMissionAsync(Guid missionId, CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            return Task.FromResult(_missions.GetValueOrDefault(missionId));
        }
    }

    private void Advance()
    {
        var now = _timeProvider.GetUtcNow();
        var elapsed = now - _lastTickUtc;
        _lastTickUtc = now;

        if (elapsed <= TimeSpan.Zero || _activeMissionId is null || _drones.Count == 0)
        {
            return;
        }

        var mission = _missions[_activeMissionId.Value];
        var maxStep = SpeedMetersPerSecond * elapsed.TotalSeconds;

        if (mission.Type == MissionType.LeaderFollowerFormation)
        {
            var leader = _drones[0];
            leader.AdvanceAlongWaypoints(mission.Waypoints, Vector3.Zero, maxStep, now);

            for (var i = 1; i < _drones.Count; i++)
            {
                _drones[i].AdvanceTowardsLeader(leader.Position, _followerOffsets[i - 1], maxStep, now);
            }
        }
        else
        {
            for (var i = 0; i < _drones.Count; i++)
            {
                var laneOffset = new Vector3(0, i * mission.SpacingMeters, 0);
                _drones[i].AdvanceAlongWaypoints(mission.Waypoints, laneOffset, maxStep, now);
            }
        }
    }

    /// <summary>
    /// Every drone starts at its own ground-level slot rather than the literal origin —
    /// stacking every drone on top of each other before takeoff would trip M2's
    /// no-collision check on tick one, and real drones do not launch from the same pad.
    /// Waypoint mode: each drone's own lane start. Formation mode: the leader's pad,
    /// plus each follower's formation offset from it — <see cref="_followerOffsets"/>
    /// captured here so `Advance` need not recompute it (and reallocate) every tick.
    /// </summary>
    private List<SimulatedDrone> BuildSwarm(Mission mission)
    {
        var drones = new List<SimulatedDrone>(mission.DroneCount);

        if (mission.Type == MissionType.LeaderFollowerFormation)
        {
            _followerOffsets = Formation.Line(mission.DroneCount - 1, mission.SpacingMeters);
            drones.Add(new SimulatedDrone("drone_1", Vector3.Zero));
            for (var i = 0; i < mission.DroneCount - 1; i++)
            {
                drones.Add(new SimulatedDrone($"drone_{i + 2}", _followerOffsets[i]));
            }
        }
        else
        {
            _followerOffsets = [];
            for (var i = 0; i < mission.DroneCount; i++)
            {
                drones.Add(new SimulatedDrone($"drone_{i + 1}", new Vector3(0, i * mission.SpacingMeters, 0)));
            }
        }

        return drones;
    }

    private sealed class SimulatedDrone(string id, Vector3 startPosition)
    {
        public string Id { get; } = id;

        public Vector3 Position { get; private set; } = startPosition;

        public int WaypointIndex { get; private set; }

        public DroneStatus Status { get; private set; } = DroneStatus.TakingOff;

        public double BatteryPercent { get; private set; } = 100.0;

        public DateTimeOffset LastUpdatedUtc { get; private set; }

        public void AdvanceAlongWaypoints(
            IReadOnlyList<Vector3> waypoints, Vector3 laneOffset, double maxStep, DateTimeOffset now)
        {
            LastUpdatedUtc = now;
            BatteryPercent = Math.Max(0, BatteryPercent - 0.01);

            if (WaypointIndex >= waypoints.Count)
            {
                Status = DroneStatus.Landed;
                return;
            }

            Status = DroneStatus.InFlight;
            var target = waypoints[WaypointIndex] + laneOffset;
            if (Position.DistanceTo(target) <= ArrivalToleranceMeters)
            {
                WaypointIndex++;
                if (WaypointIndex >= waypoints.Count)
                {
                    Status = DroneStatus.Landing;
                    return;
                }

                target = waypoints[WaypointIndex] + laneOffset;
            }

            Position = Trajectory.StepTowards(Position, target, maxStep);
        }

        /// <summary>Followers have no waypoint list; they continuously chase the leader's current position.</summary>
        public void AdvanceTowardsLeader(Vector3 leaderPosition, Vector3 offset, double maxStep, DateTimeOffset now)
        {
            LastUpdatedUtc = now;
            BatteryPercent = Math.Max(0, BatteryPercent - 0.01);
            Status = DroneStatus.InFlight;
            var target = leaderPosition + offset;
            Position = Trajectory.StepTowards(Position, target, maxStep);
        }

        public DroneState ToDroneState() => new()
        {
            Id = Id,
            Position = Position,
            BatteryPercent = BatteryPercent,
            Status = Status,
            CurrentWaypointIndex = WaypointIndex,
            LastUpdatedUtc = LastUpdatedUtc == default ? DateTimeOffset.UtcNow : LastUpdatedUtc,
        };
    }
}
