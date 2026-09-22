using SwarmApi.Application;
using SwarmApi.Domain;

namespace SwarmApi.Infrastructure;

/// <summary>
/// The zero-dependency <see cref="ISwarmBridge"/> (P8): a deterministic in-memory swarm
/// that flies each mission by elapsed time on <see cref="TimeProvider"/>. Registered when
/// no <c>RosBridge:Url</c> is configured — see docs/adr/0003-rosbridge-degrade-pattern.md —
/// and used directly by the test suites, which is what makes M3's acceptance criteria
/// checkable in CI with no container and no GPU.
///
/// Drones start on the ground on their own pads, take off, fly the mission, and land at
/// the end; a <see cref="SwarmCommand"/> pre-empts the mission for every drone.
/// </summary>
public sealed class SimulatedSwarmBridge : ISwarmBridge
{
    private const double SpeedMetersPerSecond = 2.0;
    private const double ArrivalToleranceMeters = 0.3;

    /// <summary>Battery drain while airborne, per second of simulated time (not per poll).</summary>
    private const double BatteryDrainPercentPerSecond = 0.05;

    private readonly object _lock = new();
    private readonly TimeProvider _time;
    private List<SimulatedDrone> _drones = [];
    private IReadOnlyList<Vector3> _followerOffsets = [];
    private Mission? _mission;
    private Guid? _activeMissionId;
    private SwarmCommand? _override;
    private DateTimeOffset _lastTickUtc;

    public SimulatedSwarmBridge(TimeProvider? timeProvider = null)
    {
        _time = timeProvider ?? TimeProvider.System;
        _lastTickUtc = _time.GetUtcNow();
    }

    public SwarmBridgeMode Mode => SwarmBridgeMode.Simulated;

    /// <summary>Not applicable: there is no remote swarm whose state could go stale.</summary>
    public DateTimeOffset? LastStateReceivedUtc => null;

    public Task DispatchMissionAsync(Mission mission, CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            _mission = mission;
            _activeMissionId = mission.Id;
            _override = null;
            _drones = BuildSwarm(mission);
            _lastTickUtc = _time.GetUtcNow();
        }

        return Task.CompletedTask;
    }

    public Task SendCommandAsync(SwarmCommand command, Guid? missionId, CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            Advance();
            _override = command;
            _activeMissionId = null;
        }

        return Task.CompletedTask;
    }

    public Task<SwarmState> GetStateAsync(CancellationToken cancellationToken = default)
    {
        lock (_lock)
        {
            Advance();
            var now = _time.GetUtcNow();
            return Task.FromResult(new SwarmState
            {
                Drones = _drones.Select(d => d.ToDroneState()).ToList(),
                ActiveMissionId = _activeMissionId,
                ActiveMissionComplete = _activeMissionId is not null && _drones.All(d => d.Status == DroneStatus.Landed),
                TimestampUtc = now,
                BridgeMode = SwarmBridgeMode.Simulated,
            });
        }
    }

    private void Advance()
    {
        var now = _time.GetUtcNow();
        var elapsed = now - _lastTickUtc;
        _lastTickUtc = now;

        if (elapsed <= TimeSpan.Zero || _mission is null || _drones.Count == 0)
        {
            return;
        }

        var seconds = elapsed.TotalSeconds;
        var maxStep = SpeedMetersPerSecond * seconds;

        if (_override is { } command)
        {
            foreach (var drone in _drones)
            {
                drone.ExecuteCommand(command, maxStep, seconds, now);
            }

            return;
        }

        if (_mission.Type == MissionType.LeaderFollowerFormation)
        {
            var leader = _drones[0];
            leader.FlyWaypoints(_mission.Waypoints, Vector3.Zero, maxStep, seconds, now);
            for (var i = 1; i < _drones.Count; i++)
            {
                _drones[i].FollowLeader(leader, _followerOffsets[i - 1], maxStep, seconds, now);
            }
        }
        else
        {
            for (var i = 0; i < _drones.Count; i++)
            {
                var laneOffset = new Vector3(0, i * _mission.SpacingMeters, 0);
                _drones[i].FlyWaypoints(_mission.Waypoints, laneOffset, maxStep, seconds, now);
            }
        }
    }

    /// <summary>
    /// Every drone starts on the ground at its own pad rather than the literal origin —
    /// stacking drones on top of each other before takeoff would trip M2's no-collision
    /// check on tick one, and real drones do not launch from the same pad. Waypoint mode:
    /// each drone's own lane. Formation mode: the leader's pad plus each follower's offset.
    /// </summary>
    private List<SimulatedDrone> BuildSwarm(Mission mission)
    {
        var now = _time.GetUtcNow();
        var drones = new List<SimulatedDrone>(mission.DroneCount);

        if (mission.Type == MissionType.LeaderFollowerFormation)
        {
            _followerOffsets = Formation.Offsets(mission.Formation, mission.DroneCount - 1, mission.SpacingMeters);
            drones.Add(new SimulatedDrone("drone_1", Vector3.Zero, now));
            for (var i = 0; i < mission.DroneCount - 1; i++)
            {
                drones.Add(new SimulatedDrone($"drone_{i + 2}", _followerOffsets[i], now));
            }
        }
        else
        {
            _followerOffsets = [];
            for (var i = 0; i < mission.DroneCount; i++)
            {
                drones.Add(new SimulatedDrone($"drone_{i + 1}", new Vector3(0, i * mission.SpacingMeters, 0), now));
            }
        }

        return drones;
    }

    private sealed class SimulatedDrone(string id, Vector3 pad, DateTimeOffset createdUtc)
    {
        public string Id { get; } = id;

        /// <summary>Where this drone took off from — and where return-to-launch brings it back to.</summary>
        public Vector3 Pad { get; } = pad;

        public Vector3 Position { get; private set; } = pad;

        public int WaypointIndex { get; private set; }

        // Drones exist only once a mission is dispatched, and that dispatch is the launch
        // command: they are taking off from that instant, so battery drain and every other
        // time-based quantity start then — not at whichever moment someone first reads state.
        public DroneStatus Status { get; private set; } = DroneStatus.TakingOff;

        public double BatteryPercent { get; private set; } = 100.0;

        public DateTimeOffset LastUpdatedUtc { get; private set; } = createdUtc;

        public void FlyWaypoints(
            IReadOnlyList<Vector3> waypoints, Vector3 laneOffset, double maxStep, double seconds, DateTimeOffset now)
        {
            Tick(seconds, now);
            if (Status is DroneStatus.Landed)
            {
                return;
            }

            if (WaypointIndex >= waypoints.Count)
            {
                Descend(maxStep);
                return;
            }

            var target = waypoints[WaypointIndex] + laneOffset;
            if (Position.DistanceTo(target) <= ArrivalToleranceMeters)
            {
                WaypointIndex++;
                if (WaypointIndex >= waypoints.Count)
                {
                    Descend(maxStep);
                    return;
                }

                target = waypoints[WaypointIndex] + laneOffset;
            }

            Status = WaypointIndex == 0 && Position.Z < target.Z - ArrivalToleranceMeters
                ? DroneStatus.TakingOff
                : DroneStatus.InFlight;
            Position = Trajectory.StepTowards(Position, target, maxStep);
        }

        /// <summary>Followers have no waypoint list: they chase the leader's live position, and land when it does.</summary>
        public void FollowLeader(SimulatedDrone leader, Vector3 offset, double maxStep, double seconds, DateTimeOffset now)
        {
            Tick(seconds, now);
            if (Status is DroneStatus.Landed)
            {
                return;
            }

            if (leader.Status is DroneStatus.Landing or DroneStatus.Landed)
            {
                Descend(maxStep);
                return;
            }

            Status = DroneStatus.InFlight;
            Position = Trajectory.StepTowards(Position, leader.Position + offset, maxStep);
        }

        public void ExecuteCommand(SwarmCommand command, double maxStep, double seconds, DateTimeOffset now)
        {
            Tick(seconds, now);
            if (Status is DroneStatus.Landed or DroneStatus.Idle)
            {
                return;
            }

            switch (command)
            {
                case SwarmCommand.Land:
                    Descend(maxStep);
                    break;
                case SwarmCommand.Hold:
                    Status = DroneStatus.Holding;
                    break;
                case SwarmCommand.ReturnToLaunch:
                    var overPad = new Vector3(Pad.X, Pad.Y, Position.Z);
                    if (Position.DistanceTo(overPad) > ArrivalToleranceMeters)
                    {
                        Status = DroneStatus.Returning;
                        Position = Trajectory.StepTowards(Position, overPad, maxStep);
                    }
                    else
                    {
                        Descend(maxStep);
                    }

                    break;
            }
        }

        public DroneState ToDroneState() => new()
        {
            Id = Id,
            Position = Position,
            BatteryPercent = Math.Round(BatteryPercent, 2),
            Status = Status,
            Armed = Status is not (DroneStatus.Idle or DroneStatus.Landed),
            CurrentWaypointIndex = WaypointIndex,
            LastUpdatedUtc = LastUpdatedUtc,
        };

        private void Descend(double maxStep)
        {
            var ground = new Vector3(Position.X, Position.Y, 0);
            Position = Trajectory.StepTowards(Position, ground, maxStep);
            Status = Position.Z <= 0.05 ? DroneStatus.Landed : DroneStatus.Landing;
            if (Status == DroneStatus.Landed)
            {
                Position = ground;
            }
        }

        private void Tick(double seconds, DateTimeOffset now)
        {
            LastUpdatedUtc = now;
            if (Status is not (DroneStatus.Idle or DroneStatus.Landed))
            {
                BatteryPercent = Math.Max(0, BatteryPercent - (BatteryDrainPercentPerSecond * seconds));
            }
        }
    }
}
