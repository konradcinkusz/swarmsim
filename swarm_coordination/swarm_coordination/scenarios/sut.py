"""The system under test (SUT): the swarm's software, as the simulator sees it.

A scenario never reaches into the swarm's code. It drives a ``SystemUnderTest`` through
the seams the real swarm has: one ``DroneSoftware`` per drone, which reads its own
autopilot and talks to everyone else by message, and one ``GroundSoftware``, which takes
missions and commands in the rosbridge contract's format (contracts/rosbridge/) and
reports swarm state in it. The simulator owns the network in between, so it can delay
and drop messages.

``ReferenceSwarm`` is this repository's swarm: ``DroneController``,
``MissionSupervisor`` and the swarm-state builder — the modules the ROS nodes run —
wired as the nodes wire them (drone_controller_node, mission_dispatcher_node,
swarm_state_aggregator_node). Another swarm plugs in by implementing the three protocols
below; the runner loads it with ``--sut module:attribute``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from ..drone_controller import DroneController
from ..frames import local_to_world, world_to_local
from ..mission_planning import parse_command_payload, parse_mission_payload
from ..supervisor import (
    ActiveMission,
    Assign,
    Command,
    MissionSupervisor,
    Rejected,
    Slot,
    TaskDropped,
)
from ..swarm_state import DroneReadings, build_state_message
from ..trajectory import Vector3
from .sim import Actuation, Observation

GROUND = "ground"
EVERYONE = "*"


@dataclass(frozen=True)
class Message:
    topic: str
    sender: str
    recipient: str  # a drone id, GROUND, or EVERYONE
    body: object


@dataclass(frozen=True)
class DroneInfo:
    drone_id: str
    home: Vector3  # world frame: where the drone spawns, and its local frame's origin


class DroneSoftware(Protocol):
    def step(
        self, now_s: float, observation: Observation, inbox: Sequence[Message]
    ) -> tuple[Actuation, list[Message]]: ...


class GroundSoftware(Protocol):
    def submit_mission(self, payload: str) -> None:
        """A /swarm/mission payload (contracts/rosbridge/swarm_mission.v1.schema.json)."""

    def submit_command(self, payload: str) -> None:
        """A /swarm/command payload (contracts/rosbridge/swarm_command.v1.schema.json)."""

    def step(self, now_s: float, inbox: Sequence[Message]) -> list[Message]: ...

    def report(self) -> dict:
        """The swarm state as the SUT sees it (contracts/rosbridge/swarm_state.v1)."""


class SystemUnderTest(Protocol):
    name: str

    def ground(self, fleet: Sequence[DroneInfo]) -> GroundSoftware: ...

    def drone(self, drone: DroneInfo, fleet: Sequence[DroneInfo]) -> DroneSoftware: ...


# --- the reference swarm ----------------------------------------------------------------


class ReferenceDrone:
    """drone_controller_node's wiring, minus ROS: one DroneController per drone."""

    PROGRESS_PERIOD_S = 1.0

    def __init__(self, info: DroneInfo, controller: DroneController) -> None:
        self.info = info
        self.controller = controller
        self._leader: str | None = None
        self._leader_position: Vector3 | None = None
        self._leader_heard_s: float | None = None
        self._last_progress: dict | None = None
        self._progress_sent_s: float | None = None

    def to_world(self, local: Vector3) -> Vector3:
        return local_to_world(local, self.info.home)

    def to_local(self, world: Vector3) -> Vector3:
        return world_to_local(world, self.info.home)

    def step(
        self, now_s: float, observation: Observation, inbox: Sequence[Message]
    ) -> tuple[Actuation, list[Message]]:
        for message in inbox:
            self._receive(now_s, message)

        world = None
        if observation.local_position is not None:
            world = self.to_world(observation.local_position)
        out = self.controller.tick(
            now_s,
            world,
            observation.armed,
            observation.mode,
            self._leader_position,
            self._leader_heard_s,
        )
        actuation = Actuation(
            setpoint_local=None if out.setpoint is None else self.to_local(out.setpoint),
            request_mode=out.request_mode,
            request_arm=out.request_arm,
        )

        me = self.info.drone_id
        outbox: list[Message] = []
        if world is not None:
            outbox.append(Message("pose", me, EVERYONE, world))
        progress = self.controller.progress.as_dict()
        if (
            progress != self._last_progress
            or self._progress_sent_s is None
            or now_s - self._progress_sent_s >= self.PROGRESS_PERIOD_S
        ):
            outbox.append(Message("progress", me, EVERYONE, progress))
            self._last_progress = progress
            self._progress_sent_s = now_s
        outbox.append(
            Message(
                "telemetry",
                me,
                GROUND,
                {
                    "position": world,
                    "armed": observation.armed,
                    "mode": observation.mode,
                    "battery_pct": observation.battery_pct,
                },
            )
        )
        return actuation, outbox

    def _receive(self, now_s: float, message: Message) -> None:
        body = message.body
        if message.topic == "assignment":
            self.controller.assign_path(body["mission_id"], list(body["waypoints"]))
            self._follow(None)
        elif message.topic == "slot":
            self.controller.assign_slot(body["mission_id"], body["leader"], body["offset"])
            self._follow(body["leader"])
        elif message.topic == "command":
            self.controller.command(body)
            self._follow(None)
        elif message.topic == "pose" and message.sender == self._leader:
            self._leader_position = body
            self._leader_heard_s = now_s
        elif message.topic == "progress" and message.sender == self._leader:
            if body.get("complete") and body.get("mission_id"):
                self.controller.leader_finished(body["mission_id"])

    def _follow(self, leader: str | None) -> None:
        if leader != self._leader:
            self._leader = leader
            self._leader_position = None
            self._leader_heard_s = None


class ReferenceGround:
    """mission_dispatcher_node + swarm_state_aggregator_node's wiring, minus ROS."""

    REALLOCATION_PERIOD_S = 1.0

    def __init__(self, fleet: Sequence[DroneInfo], supervisor: MissionSupervisor) -> None:
        self.supervisor = supervisor
        self._readings = {d.drone_id: DroneReadings() for d in fleet}
        self._pending: list = []
        self._active_mission: str | None = None
        self._active_drones: tuple[str, ...] = ()
        self._now_s = 0.0
        self._reallocated_s: float | None = None
        self.log: list[str] = []

    def submit_mission(self, payload: str) -> None:
        try:
            self._pending += self.supervisor.start(parse_mission_payload(payload))
        except ValueError as exc:
            self.log.append(f"rejected /swarm/mission: {exc}")

    def submit_command(self, payload: str) -> None:
        try:
            self._pending += self.supervisor.command(parse_command_payload(payload))
        except ValueError as exc:
            self.log.append(f"rejected /swarm/command: {exc}")

    def step(self, now_s: float, inbox: Sequence[Message]) -> list[Message]:
        self._now_s = now_s
        for message in inbox:
            reading = self._readings.get(message.sender)
            if reading is None:
                continue
            if message.topic == "telemetry":
                body = message.body
                if body["position"] is not None:
                    reading.position_world = body["position"]
                    reading.position_time_s = now_s
                reading.armed = body["armed"]
                reading.mode = body["mode"]
                reading.battery_pct = body["battery_pct"]
                self.supervisor.observe_battery(message.sender, body["battery_pct"])
            elif message.topic == "progress":
                body = message.body
                reading.mission_id = body.get("mission_id")
                reading.waypoint_index = body.get("waypoint_index")
                reading.waypoint_count = body.get("waypoint_count")
                reading.complete = bool(body.get("complete"))
                self.supervisor.observe_progress(
                    message.sender,
                    reading.mission_id,
                    reading.waypoint_index,
                    reading.complete,
                )

        if self._reallocated_s is None or now_s - self._reallocated_s >= self.REALLOCATION_PERIOD_S:
            self._reallocated_s = now_s
            self._pending += self.supervisor.reallocate()

        actions, self._pending = self._pending, []
        return [m for action in actions if (m := self._carry_out(action)) is not None]

    def report(self) -> dict:
        return build_state_message(
            self._readings, self._now_s, self._active_mission, list(self._active_drones)
        )

    def _carry_out(self, action) -> Message | None:
        if isinstance(action, Assign):
            body = {"mission_id": action.mission_id, "waypoints": list(action.waypoints)}
            return Message("assignment", GROUND, action.drone, body)
        if isinstance(action, Slot):
            body = {
                "mission_id": action.mission_id,
                "leader": action.leader,
                "offset": action.offset,
            }
            return Message("slot", GROUND, action.drone, body)
        if isinstance(action, Command):
            return Message("command", GROUND, action.drone, action.command)
        if isinstance(action, ActiveMission):
            self._active_mission, self._active_drones = action.mission_id, action.drones
        elif isinstance(action, Rejected):
            self.log.append(f"rejected mission {action.mission_id}: {action.reason}")
        elif isinstance(action, TaskDropped):
            self.log.append(f"{action.drone} sent home, task dropped: {action.reason}")
        return None


@dataclass
class ReferenceSwarm:
    """This repository's swarm software, as the ROS nodes configure it.

    The class fields exist for scenarios/mutants.py, which swaps one part for a broken
    one to prove the scenarios notice; the defaults are the product.
    """

    name: str = "reference"
    battery_threshold_pct: float = 20.0
    comms_timeout_s: float = 5.0
    warmup_ticks: int = 20  # drone_controller_node: 2 s of setpoints at 10 Hz
    supervisor_cls: type[MissionSupervisor] = MissionSupervisor
    controller_cls: type[DroneController] = DroneController
    drone_cls: type[ReferenceDrone] = ReferenceDrone

    def ground(self, fleet: Sequence[DroneInfo]) -> ReferenceGround:
        supervisor = self.supervisor_cls([d.drone_id for d in fleet], self.battery_threshold_pct)
        return ReferenceGround(fleet, supervisor)

    def drone(self, drone: DroneInfo, fleet: Sequence[DroneInfo]) -> ReferenceDrone:
        controller = self.controller_cls(
            drone.drone_id,
            warmup_ticks=self.warmup_ticks,
            comms_timeout_s=self.comms_timeout_s,
        )
        return self.drone_cls(drone, controller)
