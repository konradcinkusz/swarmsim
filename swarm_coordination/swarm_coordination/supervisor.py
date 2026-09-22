"""The swarm's ground-side supervisor: which drone flies what, for the whole mission.

`nodes/mission_dispatcher_node.py` feeds it what the swarm reports (missions, commands,
every drone's battery and mission progress) and publishes what it decides. The scenario
runner drives this same class inside its kinematic simulation, so a scenario that checks
battery handling checks the code the swarm runs — not a copy written for the test.

Battery policy (the one place it is decided):

* A drone whose battery is known to be below ``battery_threshold_pct`` is never given a
  task. A mission is planned onto the drones that are not, in id order; one that needs
  more of them than there are is rejected.
* A drone that drops below the threshold while it still has part of a task hands the rest
  to an idle drone above it (lowest id first, so the choice is deterministic) and is sent
  home. A leader's replacement becomes the leader its followers track.
* If no idle drone is available, the low drone is still sent home — battery safety wins —
  and the task is reported dropped. The mission then never reports complete: the swarm
  state has no way yet to say "done except for a dropped lane", and "complete" must not
  lie.
* A new mission supersedes the active one: drones the new plan does not use are sent home
  rather than left flying the old plan.

A battery nobody has reported (None) blocks nothing, and never qualifies a drone as a
replacement either. No rclpy: unit tested without ROS.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .mission_planning import CommandMessage, MissionMessage, MissionPlan, plan_mission
from .trajectory import Vector3

DEFAULT_BATTERY_THRESHOLD_PCT = 20.0


@dataclass(frozen=True)
class Assign:
    """Fly this path (world frame)."""

    drone: str
    mission_id: str
    waypoints: tuple[Vector3, ...]


@dataclass(frozen=True)
class Slot:
    """Hold ``offset`` (world frame) from ``leader``."""

    drone: str
    mission_id: str
    leader: str
    offset: Vector3


@dataclass(frozen=True)
class Command:
    """Hand the vehicle to PX4 for ``command`` (rtl | land | hold)."""

    drone: str
    command: str


@dataclass(frozen=True)
class ActiveMission:
    """The mission in progress and the drones it currently needs (None: no mission)."""

    mission_id: str | None
    drones: tuple[str, ...]


@dataclass(frozen=True)
class Rejected:
    mission_id: str
    reason: str


@dataclass(frozen=True)
class TaskDropped:
    """A low-battery drone was sent home and nobody could take over its task."""

    drone: str
    mission_id: str
    reason: str


Action = Assign | Slot | Command | ActiveMission | Rejected | TaskDropped


@dataclass
class _Progress:
    waypoint_index: int | None = None
    complete: bool = False


@dataclass
class _Mission:
    mission_id: str
    plan: MissionPlan
    progress: dict[str, _Progress] = field(default_factory=dict)
    # Sent home with a replacement flying their task: no longer part of the mission.
    retired: set[str] = field(default_factory=set)
    # Sent home with nobody to take over: still part of it, so it cannot complete.
    dropped: set[str] = field(default_factory=set)


def _id_order(drone: str) -> tuple[int, str]:
    number = drone.rsplit("_", 1)[-1]
    return (int(number), drone) if number.isdigit() else (1 << 30, drone)


class MissionSupervisor:
    def __init__(
        self,
        drones: Sequence[str],
        battery_threshold_pct: float = DEFAULT_BATTERY_THRESHOLD_PCT,
    ) -> None:
        self.drones = sorted(drones, key=_id_order)
        self.battery_threshold_pct = battery_threshold_pct
        self._battery: dict[str, float | None] = {d: None for d in self.drones}
        self._mission: _Mission | None = None

    # --- what the swarm reports ------------------------------------------------------

    def observe_battery(self, drone: str, battery_pct: float | None) -> None:
        if drone in self._battery:
            self._battery[drone] = battery_pct

    def observe_progress(
        self, drone: str, mission_id: str | None, waypoint_index: int | None, complete: bool
    ) -> None:
        mission = self._mission
        if mission is None or mission_id != mission.mission_id:
            return
        progress = mission.progress.setdefault(drone, _Progress())
        progress.waypoint_index = waypoint_index
        progress.complete = complete

    # --- what the operator asks for ---------------------------------------------------

    def start(self, mission: MissionMessage) -> list[Action]:
        """Plan ``mission`` onto the drones fit to fly it, or reject it."""
        eligible = [d for d in self.drones if not self._low(d)]
        if len(eligible) < mission.drone_count:
            low = [d for d in self.drones if self._low(d)]
            reason = (
                f"needs {mission.drone_count} drone(s) but only {len(eligible)} of "
                f"{self.drones} are fit to fly"
                + (
                    f" ({', '.join(low)} below {self.battery_threshold_pct:g}% battery)"
                    if low
                    else ""
                )
            )
            return [Rejected(mission.mission_id, reason)]

        superseded = set(self.mission_drones())
        plan = plan_mission(mission, eligible[: mission.drone_count])
        self._mission = _Mission(mission.mission_id, plan)
        actions: list[Action] = [
            Command(drone, "rtl") for drone in sorted(superseded - set(plan.drones), key=_id_order)
        ]
        actions += [
            Assign(drone, plan.mission_id, tuple(path)) for drone, path in plan.paths.items()
        ]
        actions += [
            Slot(drone, plan.mission_id, leader, offset)
            for drone, (leader, offset) in plan.followers.items()
        ]
        actions.append(ActiveMission(plan.mission_id, tuple(self._mission_drones())))
        return actions

    def command(self, message: CommandMessage) -> list[Action]:
        """A swarm-wide command reaches every drone and ends the mission in progress."""
        self._mission = None
        return [Command(drone, message.command) for drone in self.drones] + [
            ActiveMission(None, ())
        ]

    # --- the periodic decision --------------------------------------------------------

    def reallocate(self) -> list[Action]:
        """Hand each low-battery drone's unfinished task to an idle drone; send it home."""
        mission = self._mission
        if mission is None:
            return []
        actions: list[Action] = []
        for drone in list(self._mission_drones()):
            if drone in mission.dropped or not self._low(drone) or self._finished(drone):
                continue
            replacement = self._replacement()
            actions.append(Command(drone, "rtl"))
            if replacement is None:
                mission.dropped.add(drone)
                actions.append(
                    TaskDropped(
                        drone,
                        mission.mission_id,
                        f"battery {self._battery[drone]:.1f}% is below "
                        f"{self.battery_threshold_pct:g}% and no idle drone above it is left",
                    )
                )
                continue
            mission.retired.add(drone)
            actions += self._hand_over(drone, replacement)
        if actions:
            actions.append(ActiveMission(mission.mission_id, tuple(self._mission_drones())))
        return actions

    @property
    def active_mission_id(self) -> str | None:
        return self._mission.mission_id if self._mission else None

    def mission_drones(self) -> list[str]:
        """The drones the active mission currently needs (for completion)."""
        return self._mission_drones() if self._mission else []

    # --- internals ----------------------------------------------------------------------

    def _low(self, drone: str) -> bool:
        battery = self._battery.get(drone)
        return battery is not None and battery < self.battery_threshold_pct

    def _finished(self, drone: str) -> bool:
        progress = self._mission.progress.get(drone) if self._mission else None
        return progress is not None and progress.complete

    def _mission_drones(self) -> list[str]:
        plan = self._mission.plan
        return sorted([*plan.paths, *plan.followers], key=_id_order)

    def _replacement(self) -> str | None:
        mission = self._mission
        busy = {*mission.plan.paths, *mission.plan.followers, *mission.retired, *mission.dropped}
        for drone in self.drones:
            battery = self._battery.get(drone)
            if drone not in busy and battery is not None and battery >= self.battery_threshold_pct:
                return drone
        return None

    def _hand_over(self, low: str, replacement: str) -> list[Action]:
        mission = self._mission
        plan = mission.plan
        actions: list[Action] = []
        if low in plan.paths:
            path = plan.paths.pop(low)
            progress = mission.progress.get(low)
            start = progress.waypoint_index if progress and progress.waypoint_index else 0
            remaining = path[min(start, len(path) - 1) :]
            plan.paths[replacement] = remaining
            actions.append(Assign(replacement, mission.mission_id, tuple(remaining)))
            # Followers of the drone going home follow its replacement instead.
            for follower, (leader, offset) in list(plan.followers.items()):
                if leader == low:
                    plan.followers[follower] = (replacement, offset)
                    actions.append(Slot(follower, mission.mission_id, replacement, offset))
        else:
            leader, offset = plan.followers.pop(low)
            plan.followers[replacement] = (leader, offset)
            actions.append(Slot(replacement, mission.mission_id, leader, offset))
        return actions
