"""Broken swarms: the reference swarm with one behaviour taken out, on purpose.

A scenario that passes proves little until it has been seen to fail. The mutation check
runs every scenario against each mutant below; a scenario that no mutant fails is
toothless — it would not notice if the behaviour it is named after disappeared — and a
mutant no scenario fails is a behaviour the suite does not guard. Each mutant is a
plausible regression (a dropped offset, a skipped frame conversion, a timeout set wrong),
not a random edit, so a kill says something about the suite.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..drone_controller import DroneController
from ..supervisor import MissionSupervisor
from ..trajectory import Vector3
from .sut import ReferenceDrone, ReferenceSwarm


class _NeverLandsController(DroneController):
    def _task_done(self) -> bool:
        return False  # finishes its path and hovers there for good


class _OffsetDroppedController(DroneController):
    def assign_slot(self, mission_id: str, leader: str, offset: Vector3) -> None:
        super().assign_slot(mission_id, leader, Vector3(0.0, 0.0, 0.0))


class _NoFramesDrone(ReferenceDrone):
    def to_world(self, local: Vector3) -> Vector3:
        return local  # the drone's own frame taken for the world's

    def to_local(self, world: Vector3) -> Vector3:
        return world


class _DeafToCommandsDrone(ReferenceDrone):
    def _receive(self, now_s, message) -> None:
        if message.topic != "command":
            super()._receive(now_s, message)


class _NoReallocationSupervisor(MissionSupervisor):
    def reallocate(self):
        return []


class _BatteryBlindSupervisor(MissionSupervisor):
    def _low(self, drone: str) -> bool:
        return False


@dataclass(frozen=True)
class Mutant:
    name: str
    breaks: str
    sut: ReferenceSwarm


def _mutant(name: str, breaks: str, **parts) -> Mutant:
    return Mutant(name, breaks, replace(ReferenceSwarm(), name=f"mutant:{name}", **parts))


MUTANTS: tuple[Mutant, ...] = (
    _mutant(
        "never_lands",
        "a drone that finished its task hovers instead of handing over to AUTO.LAND",
        controller_cls=_NeverLandsController,
    ),
    _mutant(
        "formation_offset_dropped",
        "followers are sent to the leader's own position instead of their slots",
        controller_cls=_OffsetDroppedController,
    ),
    _mutant(
        "no_frame_conversion",
        "each drone treats its local frame (origin: its own pad) as the world frame",
        drone_cls=_NoFramesDrone,
    ),
    _mutant(
        "deaf_to_commands",
        "drones ignore operator commands (land, rtl, hold)",
        drone_cls=_DeafToCommandsDrone,
    ),
    _mutant(
        "no_battery_reallocation",
        "a drone low on battery keeps its task; nobody takes over",
        supervisor_cls=_NoReallocationSupervisor,
    ),
    _mutant(
        "battery_blind",
        "battery levels are ignored everywhere: when planning and in flight",
        supervisor_cls=_BatteryBlindSupervisor,
    ),
    _mutant(
        "no_comms_timeout",
        "a follower that lost its leader holds its slot forever instead of going home",
        comms_timeout_s=float("inf"),
    ),
    _mutant(
        "hair_trigger_comms_timeout",
        "a follower goes home after 0.3 s without its leader, not 5 s",
        comms_timeout_s=0.3,
    ),
)
