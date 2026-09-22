"""Getting PX4 into OFFBOARD mode and armed, the way PX4 requires it.

PX4 only accepts OFFBOARD once it has been receiving setpoints for a while (its offboard
signal must be present before the switch), it may reject a request that arrives before
MAVROS's services are up, and a request is not a result. So: stream setpoints first,
then ask for the mode, then for arming — and keep asking at a fixed interval until the
autopilot's own reported state says it happened. Once the autopilot leaves OFFBOARD on its
own (a failsafe, a pilot, an autonomous mode we asked for), the sequencer stops streaming
rather than fight it. No rclpy: unit tested without ROS.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Phase(Enum):
    IDLE = "idle"
    WARMUP = "warmup"
    REQUEST_MODE = "request_mode"
    REQUEST_ARM = "request_arm"
    ACTIVE = "active"
    RELEASED = "released"


@dataclass(frozen=True)
class OffboardStep:
    """What the adapter should do on this tick."""

    stream_setpoint: bool
    request_offboard: bool = False
    request_arm: bool = False


class OffboardSequencer:
    def __init__(self, warmup_ticks: int = 20, retry_interval_s: float = 1.0) -> None:
        if warmup_ticks < 1:
            raise ValueError("warmup_ticks must be at least 1")
        self.warmup_ticks = warmup_ticks
        self.retry_interval_s = retry_interval_s
        self.phase = Phase.IDLE
        self._streamed = 0
        self._last_request_s: float | None = None

    def start(self) -> None:
        """A new task needs offboard control: stream first, then ask."""
        self.phase = Phase.WARMUP
        self._streamed = 0
        self._last_request_s = None

    def release(self) -> None:
        """Stop streaming and stop asking — the autopilot owns the vehicle now."""
        self.phase = Phase.RELEASED

    def _due(self, now_s: float) -> bool:
        if self._last_request_s is None or now_s - self._last_request_s >= self.retry_interval_s:
            self._last_request_s = now_s
            return True
        return False

    def step(self, now_s: float, armed: bool | None, mode: str | None) -> OffboardStep:
        if self.phase in (Phase.IDLE, Phase.RELEASED):
            return OffboardStep(stream_setpoint=False)

        if self.phase == Phase.WARMUP:
            self._streamed += 1
            if self._streamed >= self.warmup_ticks:
                self.phase = Phase.REQUEST_MODE
            return OffboardStep(stream_setpoint=True)

        if self.phase == Phase.REQUEST_MODE:
            if mode == "OFFBOARD":
                self.phase = Phase.REQUEST_ARM
                self._last_request_s = None
            else:
                return OffboardStep(stream_setpoint=True, request_offboard=self._due(now_s))

        if self.phase == Phase.REQUEST_ARM:
            if mode != "OFFBOARD":
                self.phase = Phase.REQUEST_MODE
                return OffboardStep(stream_setpoint=True, request_offboard=self._due(now_s))
            if armed:
                self.phase = Phase.ACTIVE
            else:
                return OffboardStep(stream_setpoint=True, request_arm=self._due(now_s))

        # ACTIVE: keep streaming while PX4 stays in OFFBOARD; once it leaves on its own,
        # let go rather than drag it back.
        if mode is not None and mode != "OFFBOARD":
            self.phase = Phase.RELEASED
            return OffboardStep(stream_setpoint=False)
        return OffboardStep(stream_setpoint=True)
