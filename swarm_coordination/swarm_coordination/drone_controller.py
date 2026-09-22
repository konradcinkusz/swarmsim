"""Everything one drone decides, as a pure state machine the ROS node only drives.

A drone is idle until it gets a task: a **path** (a waypoint list, in the world frame) or
a **slot** (a leader to follow at a fixed world-frame offset). It then takes offboard
control (:mod:`offboard`), flies the task, and hands the vehicle back to PX4 when the task
is done — landing where a path ends, or where the leader lands — or when a swarm command
pre-empts it (:mod:`commands`). It reports its progress so the swarm can tell when a
mission is complete. Everything here is in the world frame; the node converts to and from
the drone's own local frame (:mod:`frames`). No rclpy: unit tested without ROS.
"""

from __future__ import annotations

from dataclasses import dataclass

from .commands import mode_for_command
from .offboard import OffboardSequencer, Phase
from .trajectory import Vector3, step_towards
from .waypoints import WaypointQueue


@dataclass(frozen=True)
class ControllerOutput:
    """What the adapter should do on this tick."""

    setpoint: Vector3 | None = None
    request_mode: str | None = None
    request_arm: bool = False


@dataclass(frozen=True)
class Progress:
    mission_id: str | None
    waypoint_index: int | None
    waypoint_count: int | None
    complete: bool

    def as_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "waypoint_index": self.waypoint_index,
            "waypoint_count": self.waypoint_count,
            "complete": self.complete,
        }


class DroneController:
    def __init__(
        self,
        drone_id: str,
        tolerance_m: float = 0.5,
        max_step_m: float = 2.0,
        warmup_ticks: int = 20,
        retry_interval_s: float = 1.0,
    ) -> None:
        self.drone_id = drone_id
        self.tolerance_m = tolerance_m
        self.max_step_m = max_step_m
        self._offboard = OffboardSequencer(warmup_ticks, retry_interval_s)
        self._retry_interval_s = retry_interval_s
        self._mission_id: str | None = None
        self._queue: WaypointQueue | None = None
        self._leader: str | None = None
        self._offset = Vector3(0.0, 0.0, 0.0)
        self._leader_done = False
        self._handover_mode: str | None = None
        self._last_handover_request_s: float | None = None
        self._complete = False

    # --- inputs ------------------------------------------------------------------------

    def assign_path(self, mission_id: str, waypoints: list[Vector3]) -> None:
        if not waypoints:
            raise ValueError("a path needs at least one waypoint")
        self._begin(mission_id)
        self._queue = WaypointQueue(waypoints=list(waypoints), tolerance_m=self.tolerance_m)

    def assign_slot(self, mission_id: str, leader: str, offset: Vector3) -> None:
        self._begin(mission_id)
        self._leader = leader
        self._offset = offset

    def leader_finished(self, mission_id: str) -> None:
        """The leader completed its path for ``mission_id``: a follower lands with it."""
        if mission_id == self._mission_id and self._leader is not None:
            self._leader_done = True

    def command(self, command: str) -> None:
        """A swarm-wide override: hand the vehicle to PX4's mode for it, now."""
        self._handover(mode_for_command(command))
        self._complete = False

    # --- the control loop --------------------------------------------------------------

    def tick(
        self,
        now_s: float,
        position: Vector3 | None,
        armed: bool | None,
        mode: str | None,
        leader_position: Vector3 | None = None,
    ) -> ControllerOutput:
        if self._handover_mode is not None:
            return self._keep_handing_over(now_s, armed, mode)

        if position is None or (self._queue is None and self._leader is None):
            return ControllerOutput()

        target = self._target(position, leader_position)
        if target is None:
            return ControllerOutput()

        if self._task_done():
            self._complete = self._queue is not None or self._leader is not None
            self._handover("AUTO.LAND")
            return self._keep_handing_over(now_s, armed, mode)

        step = self._offboard.step(now_s, armed, mode)
        if self._offboard.phase == Phase.RELEASED:
            # PX4 left OFFBOARD on its own (failsafe, pilot): not ours to fight.
            return ControllerOutput()
        return ControllerOutput(
            setpoint=target if step.stream_setpoint else None,
            request_mode="OFFBOARD" if step.request_offboard else None,
            request_arm=step.request_arm,
        )

    @property
    def progress(self) -> Progress:
        if self._queue is not None:
            count = len(self._queue.waypoints)
            index = min(count - self._queue.remaining, count)
            return Progress(self._mission_id, index, count, self._complete)
        return Progress(self._mission_id, None, None, self._complete)

    # --- internals -----------------------------------------------------------------------

    def _begin(self, mission_id: str) -> None:
        self._mission_id = mission_id
        self._queue = None
        self._leader = None
        self._leader_done = False
        self._handover_mode = None
        self._complete = False
        self._offboard.start()

    def _target(self, position: Vector3, leader_position: Vector3 | None) -> Vector3 | None:
        if self._queue is not None:
            self._queue.advance(position)
            goal = self._queue.current
            return position if goal is None else step_towards(position, goal, self.max_step_m)
        if leader_position is None:
            return None
        return leader_position + self._offset

    def _task_done(self) -> bool:
        if self._queue is not None:
            return self._queue.is_complete
        return self._leader_done

    def _handover(self, px4_mode: str) -> None:
        self._offboard.release()
        self._handover_mode = px4_mode
        self._last_handover_request_s = None

    def _keep_handing_over(
        self, now_s: float, armed: bool | None, mode: str | None
    ) -> ControllerOutput:
        # Keep asking until PX4 reports the mode (or has already landed and disarmed).
        if mode == self._handover_mode or armed is False:
            return ControllerOutput()
        if (
            self._last_handover_request_s is None
            or now_s - self._last_handover_request_s >= self._retry_interval_s
        ):
            self._last_handover_request_s = now_s
            return ControllerOutput(request_mode=self._handover_mode)
        return ControllerOutput()
