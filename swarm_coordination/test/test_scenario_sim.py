"""L0's autopilot keeps the PX4 rules the swarm's software depends on."""

import random

import pytest

from swarm_coordination.scenarios.sim import Actuation, Vehicle, VehicleLimits, Wind, WorldConfig
from swarm_coordination.trajectory import Vector3

HOME = Vector3(0.0, 3.0, 0.0)
CALM = Vector3(0.0, 0.0, 0.0)
FIVE_UP = Vector3(0.0, 0.0, 5.0)
DT = 0.1


def _vehicle(**limits):
    return Vehicle("drone_2", HOME, 100.0, VehicleLimits(**limits))


def _run(vehicle, seconds, actuation=lambda t: Actuation(), start=0.0, wind=CALM):
    t = start
    for _ in range(int(round(seconds / DT))):
        vehicle.actuate(t, actuation(t))
        vehicle.step(t, DT, wind, drain_pct_per_s=0.05)
        t = round(t + DT, 6)
    return t


def _take_off(vehicle, target_local=FIVE_UP, seconds=8.0):
    def actuation(t):
        if t < 0.25:
            return Actuation(setpoint_local=target_local)
        if t < 0.35:
            return Actuation(setpoint_local=target_local, request_mode="OFFBOARD")
        if t < 0.45:
            return Actuation(setpoint_local=target_local, request_arm=True)
        return Actuation(setpoint_local=target_local)

    return _run(vehicle, seconds, actuation)


def test_offboard_and_arming_are_refused_without_a_setpoint_stream():
    vehicle = _vehicle()

    vehicle.actuate(0.0, Actuation(request_mode="OFFBOARD"))
    vehicle.actuate(0.1, Actuation(request_arm=True))

    assert vehicle.mode == "AUTO.LOITER" and not vehicle.armed


def test_setpoints_in_the_local_frame_fly_the_drone_relative_to_its_home():
    vehicle = _vehicle()

    _take_off(vehicle)

    assert vehicle.armed and vehicle.mode == "OFFBOARD"
    assert vehicle.position.distance_to(Vector3(0.0, 3.0, 5.0)) < 0.1
    assert (
        vehicle.observe(random.Random(0), 0.0).local_position.distance_to(Vector3(0.0, 0.0, 5.0))
        < 0.1
    )


def test_speed_and_climb_are_limited():
    vehicle = _vehicle(max_speed_m_s=5.0, max_climb_m_s=3.0)
    far = Vector3(100.0, 0.0, 100.0)

    _take_off(vehicle, target_local=far, seconds=2.0)

    moved = vehicle.position - HOME
    assert moved.z <= 3.0 * 1.6 + 1e-6  # at most 1.6 s of climbing at 3 m/s
    assert moved.x <= 5.0 * 1.6 + 1e-6


def test_a_setpoint_stream_that_stops_drops_the_drone_into_loiter():
    vehicle = _vehicle(offboard_loss_timeout_s=1.0)
    t = _take_off(vehicle)

    _run(vehicle, 1.5, start=t)  # no more setpoints

    assert vehicle.mode == "AUTO.LOITER" and vehicle.armed and vehicle.airborne


def test_land_descends_in_place_and_disarms_after_touchdown():
    vehicle = _vehicle(land_disarm_s=2.0)
    t = _take_off(vehicle)
    vehicle.actuate(t, Actuation(request_mode="AUTO.LAND"))

    _run(vehicle, 15.0, start=t)

    assert not vehicle.armed
    assert vehicle.position.distance_to(Vector3(0.0, 3.0, 0.0)) < 0.1


def test_rtl_climbs_flies_home_and_lands_on_the_pad():
    vehicle = _vehicle(rtl_altitude_m=10.0)
    t = _take_off(vehicle, target_local=Vector3(20.0, 0.0, 5.0), seconds=15.0)
    vehicle.actuate(t, Actuation(request_mode="AUTO.RTL"))
    peak = 0.0
    for _ in range(600):
        vehicle.step(t, DT, Vector3(0, 0, 0), 0.0)
        peak = max(peak, vehicle.position.z)
        t += DT

    assert peak >= 9.7
    assert not vehicle.armed
    assert vehicle.position.distance_to(HOME) < 0.6


def test_a_drone_armed_but_never_lifted_off_disarms_itself():
    vehicle = _vehicle(preflight_disarm_s=10.0)

    _take_off(vehicle, target_local=Vector3(0.0, 0.0, 0.0), seconds=12.0)

    assert not vehicle.armed


def test_a_flat_battery_lands_the_drone_where_it_is():
    vehicle = _vehicle()
    t = _take_off(vehicle, target_local=Vector3(5.0, 0.0, 5.0))
    vehicle.battery_pct = 0.01

    _run(vehicle, 12.0, actuation=lambda _: Actuation(setpoint_local=Vector3(50, 0, 5)), start=t)

    assert vehicle.mode == "AUTO.LAND" and not vehicle.armed
    assert vehicle.position.distance_to(Vector3(5.0, 3.0, 0.0)) < 1.0


def test_battery_drains_only_while_airborne():
    vehicle = _vehicle()
    _run(vehicle, 10.0)
    assert vehicle.battery_pct == 100.0

    _take_off(vehicle, seconds=10.0)

    assert 99.0 < vehicle.battery_pct < 100.0


def test_the_wind_the_position_loop_does_not_cancel_pushes_the_drone():
    calm, windy = _vehicle(), _vehicle(wind_rejection=0.8)
    _take_off(calm)
    _take_off(windy)

    _run(
        windy,
        5.0,
        actuation=lambda _: Actuation(setpoint_local=Vector3(0, 0, 5)),
        start=8.0,
        wind=Vector3(5.0, 0.0, 0.0),
    )

    # 20 % of 5 m/s pushes; the P loop settles where it cancels it: 1 m/s ÷ 1/s = 1 m off.
    assert 0.5 < windy.position.x - calm.position.x < 1.1


def test_gps_noise_moves_what_the_software_reads_never_the_truth():
    vehicle = _vehicle()
    rng = random.Random(7)

    readings = [vehicle.observe(rng, 0.5).local_position for _ in range(200)]

    assert vehicle.position == HOME
    spread = max(abs(r.x) for r in readings)
    assert 0.5 < spread < 3.0


@pytest.mark.parametrize("seed", [1, 2])
def test_gusts_are_reproducible_from_the_seed(seed):
    config = WorldConfig(wind_mean=Vector3(1.0, 0.0, 0.0), wind_gust_std_m_s=1.0)

    first = [Wind(config, random.Random(seed)).step(DT) for _ in range(3)]
    second = [Wind(config, random.Random(seed)).step(DT) for _ in range(3)]

    assert first == second


def test_gusts_have_the_configured_spread():
    config = WorldConfig(wind_gust_std_m_s=2.0, gust_time_constant_s=2.0)
    wind = Wind(config, random.Random(3))

    samples = [wind.step(DT).x for _ in range(20000)]
    mean = sum(samples) / len(samples)
    std = (sum((s - mean) ** 2 for s in samples) / len(samples)) ** 0.5

    assert abs(mean) < 0.4 and 1.5 < std < 2.5
