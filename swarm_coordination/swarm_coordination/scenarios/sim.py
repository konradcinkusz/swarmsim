"""L0: a seeded kinematic stand-in for PX4 SITL + Gazebo, fast enough for every push.

Each drone is a point mass under a PX4-like autopilot:

* OFFBOARD flies toward the latest position setpoint (local frame, relative to the
  drone's home) under a proportional gain with PX4-style limits: horizontal speed, climb
  and descent rates. PX4's rules are kept where the swarm's software depends on them:
  OFFBOARD is refused, and arming too, unless setpoints are arriving; a setpoint stream
  that stops for ``offboard_loss_timeout_s`` drops the drone into AUTO.LOITER.
* AUTO.LAND descends in place, AUTO.RTL climbs to ``rtl_altitude_m``, flies home and
  lands, AUTO.LOITER holds where it was. A drone on the ground after flying disarms
  itself after ``land_disarm_s``; one armed but never lifted off, after
  ``preflight_disarm_s``.
* Wind is a mean plus a seeded gust (an Ornstein-Uhlenbeck process), of which the
  position loop cancels ``wind_rejection``; GPS noise is Gaussian per axis on the
  position the drone's software reads, never on the truth the assertions judge.
* Battery drains per airborne second; a drone that runs dry lands where it is.

It deliberately omits attitude dynamics, motor and sensor models, estimator behaviour
and collisions with each other (a breach of separation is measured, not simulated). A
scenario that passes here has shown the swarm's *decisions* are right; whether PX4 flies
them the same way is the SITL smoke's question (L1). Same seed, same run, bit for bit.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..trajectory import Vector3

GROUND_TOLERANCE_M = 0.05


@dataclass(frozen=True)
class VehicleLimits:
    """PX4 v1.15 defaults where one exists (MPC_*, COM_*); L0's own choice otherwise."""

    max_speed_m_s: float = 5.0
    max_climb_m_s: float = 3.0  # MPC_Z_VEL_MAX_UP
    max_descent_m_s: float = 1.5
    land_speed_m_s: float = 0.7  # MPC_LAND_SPEED
    position_gain_per_s: float = 1.0
    rtl_altitude_m: float = 10.0
    offboard_loss_timeout_s: float = 1.0  # COM_OF_LOSS_T
    preflight_disarm_s: float = 10.0  # COM_DISARM_PRFLT
    land_disarm_s: float = 2.0  # COM_DISARM_LAND
    wind_rejection: float = 0.8


@dataclass(frozen=True)
class WorldConfig:
    dt_s: float = 0.1
    wind_mean: Vector3 = field(default_factory=lambda: Vector3(0.0, 0.0, 0.0))
    wind_gust_std_m_s: float = 0.0
    gust_time_constant_s: float = 5.0
    gps_noise_std_m: float = 0.0
    battery_drain_pct_per_s: float = 0.05
    limits: VehicleLimits = field(default_factory=VehicleLimits)


@dataclass(frozen=True)
class Observation:
    """What a drone's own software reads from its autopilot (MAVROS, in the real swarm)."""

    local_position: Vector3 | None  # relative to home, with GPS noise
    armed: bool
    mode: str
    battery_pct: float


@dataclass(frozen=True)
class Actuation:
    """What a drone's software asks its autopilot for on one tick."""

    setpoint_local: Vector3 | None = None
    request_mode: str | None = None
    request_arm: bool = False


def _clamp_velocity(v: Vector3, limits: VehicleLimits) -> Vector3:
    horizontal = math.hypot(v.x, v.y)
    x, y = v.x, v.y
    if horizontal > limits.max_speed_m_s:
        scale = limits.max_speed_m_s / horizontal
        x, y = x * scale, y * scale
    z = max(-limits.max_descent_m_s, min(limits.max_climb_m_s, v.z))
    return Vector3(x, y, z)


class Vehicle:
    """One drone: the truth the assertions judge, and the autopilot the software talks to."""

    def __init__(
        self, drone_id: str, home: Vector3, battery_pct: float, limits: VehicleLimits
    ) -> None:
        self.drone_id = drone_id
        self.home = home
        self.position = home
        self.battery_pct = battery_pct
        self.limits = limits
        self.armed = False
        self.mode = "AUTO.LOITER"
        self.took_off = False
        self._setpoint: Vector3 | None = None  # world frame
        self._setpoint_time: float | None = None
        self._hold: Vector3 = home
        self._armed_at: float | None = None
        self._grounded_since: float | None = None
        self._rtl_phase = "climb"

    @property
    def airborne(self) -> bool:
        return self.position.z > GROUND_TOLERANCE_M

    # --- the autopilot's interface ----------------------------------------------------

    def observe(self, rng: random.Random, gps_noise_std_m: float) -> Observation:
        local = self.position - self.home
        if gps_noise_std_m > 0:
            local = local + Vector3(
                rng.gauss(0.0, gps_noise_std_m),
                rng.gauss(0.0, gps_noise_std_m),
                rng.gauss(0.0, gps_noise_std_m),
            )
        return Observation(local, self.armed, self.mode, round(self.battery_pct, 3))

    def actuate(self, now_s: float, actuation: Actuation) -> None:
        if actuation.setpoint_local is not None:
            self._setpoint = actuation.setpoint_local + self.home
            self._setpoint_time = now_s
        if actuation.request_mode is not None:
            self._request_mode(now_s, actuation.request_mode)
        if actuation.request_arm and not self.armed:
            if self.mode == "OFFBOARD" and self._setpoints_fresh(now_s):
                self.armed = True
                self.took_off = False
                self._armed_at = now_s
                self._grounded_since = None

    def _setpoints_fresh(self, now_s: float) -> bool:
        return (
            self._setpoint_time is not None
            and now_s - self._setpoint_time <= self.limits.offboard_loss_timeout_s
        )

    def _request_mode(self, now_s: float, mode: str) -> None:
        if mode == "OFFBOARD" and not self._setpoints_fresh(now_s):
            return  # PX4 refuses OFFBOARD without an offboard signal
        if mode not in ("OFFBOARD", "AUTO.LAND", "AUTO.RTL", "AUTO.LOITER"):
            return
        if mode != self.mode:
            self._enter(mode)

    def _enter(self, mode: str) -> None:
        self.mode = mode
        self._hold = self.position
        self._rtl_phase = "climb"

    # --- physics ------------------------------------------------------------------------

    def step(self, now_s: float, dt_s: float, disturbance: Vector3, drain_pct_per_s: float) -> None:
        if not self.armed:
            return

        if self.airborne:
            self.battery_pct = max(0.0, self.battery_pct - drain_pct_per_s * dt_s)
            if self.battery_pct == 0.0 and self.mode != "AUTO.LAND":
                self._enter("AUTO.LAND")  # a flat battery comes down where it is

        if self.mode == "OFFBOARD" and not self._setpoints_fresh(now_s):
            self._enter("AUTO.LOITER")  # offboard loss failsafe

        velocity = _clamp_velocity(self._command(), self.limits)
        drift = Vector3(0.0, 0.0, 0.0)
        if self.airborne:
            drift = disturbance.scale(1.0 - self.limits.wind_rejection)
        elif velocity.z <= 0.0:
            velocity = Vector3(0.0, 0.0, 0.0)  # on the ground and not climbing: no taxiing
        moved = self.position + (velocity + drift).scale(dt_s)
        if moved.z < 0.0:
            moved = Vector3(moved.x, moved.y, 0.0)
        if moved.z > GROUND_TOLERANCE_M:
            self.took_off = True
        self.position = moved
        self._auto_disarm(now_s)

    def _command(self) -> Vector3:
        gain = self.limits.position_gain_per_s
        if self.mode == "OFFBOARD" and self._setpoint is not None:
            return (self._setpoint - self.position).scale(gain)
        if self.mode == "AUTO.LAND":
            hold = Vector3(self._hold.x, self._hold.y, self.position.z)
            return (hold - self.position).scale(gain) + Vector3(
                0.0, 0.0, -self.limits.land_speed_m_s
            )
        if self.mode == "AUTO.RTL":
            return self._rtl_command(gain)
        return (self._hold - self.position).scale(gain)  # AUTO.LOITER

    def _rtl_command(self, gain: float) -> Vector3:
        altitude = max(self.limits.rtl_altitude_m, self._hold.z)
        above_home = Vector3(self.home.x, self.home.y, altitude)
        if self._rtl_phase == "climb":
            if self.position.z >= altitude - 0.2:
                self._rtl_phase = "return"
            else:
                return Vector3(0.0, 0.0, self.limits.max_climb_m_s)
        if self._rtl_phase == "return":
            if math.hypot(self.position.x - self.home.x, self.position.y - self.home.y) <= 0.5:
                self._rtl_phase = "descend"
            else:
                return (above_home - self.position).scale(gain)
        hold = Vector3(self.home.x, self.home.y, self.position.z)
        return (hold - self.position).scale(gain) + Vector3(0.0, 0.0, -self.limits.land_speed_m_s)

    def _auto_disarm(self, now_s: float) -> None:
        if self.airborne:
            self._grounded_since = None
            return
        if not self.took_off:
            if (
                self._armed_at is not None
                and now_s - self._armed_at >= self.limits.preflight_disarm_s
            ):
                self._disarm()
            return
        if self._grounded_since is None:
            self._grounded_since = now_s
        elif now_s - self._grounded_since >= self.limits.land_disarm_s:
            self._disarm()

    def _disarm(self) -> None:
        self.armed = False
        self._armed_at = None
        self._grounded_since = None
        self._setpoint = None
        self._setpoint_time = None


class Wind:
    """The mean wind plus a seeded gust, shared by every drone (one weather, one swarm)."""

    def __init__(self, config: WorldConfig, rng: random.Random) -> None:
        self._mean = config.wind_mean
        self._std = config.wind_gust_std_m_s
        self._tau = max(config.gust_time_constant_s, config.dt_s)
        self._rng = rng
        self._gust = Vector3(0.0, 0.0, 0.0)

    def step(self, dt_s: float) -> Vector3:
        if self._std > 0:
            # Ornstein-Uhlenbeck: stationary standard deviation ``std``, correlation ``tau``.
            decay = math.exp(-dt_s / self._tau)
            scale = self._std * math.sqrt(1.0 - decay * decay)
            self._gust = Vector3(
                self._gust.x * decay + self._rng.gauss(0.0, scale),
                self._gust.y * decay + self._rng.gauss(0.0, scale),
                self._gust.z * decay + self._rng.gauss(0.0, scale * 0.3),
            )
        return self._mean + self._gust
