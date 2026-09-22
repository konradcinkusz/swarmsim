import math

import pytest

from swarm_coordination.swarm_state import (
    DroneReadings,
    battery_percent,
    build_state_message,
    mission_complete,
)
from swarm_coordination.trajectory import Vector3

MISSION = "3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c"


@pytest.mark.parametrize(
    ("fraction", "expected"),
    [(0.875, 87.5), (1.2, 100.0), (float("nan"), None), (None, None), (-1.0, None)],
)
def test_battery_fraction_becomes_a_percentage_or_unknown(fraction, expected):
    assert battery_percent(fraction) == expected


def test_a_drone_never_heard_from_is_left_out_and_unknowns_stay_null():
    readings = {
        "drone_1": DroneReadings(position_world=Vector3(1.0, 2.0, 3.0), position_time_s=9.5),
        "drone_2": DroneReadings(armed=True),
    }

    message = build_state_message(readings, now_s=10.0)

    assert message["frame"] == "world_enu"
    assert message["mission"] is None
    (drone,) = message["drones"]
    assert drone["id"] == "drone_1"
    assert drone["age_s"] == 0.5
    assert drone["battery_pct"] is None and drone["armed"] is None and drone["mode"] is None


def test_drones_are_listed_in_numeric_order():
    readings = {f"drone_{n}": DroneReadings(position_world=Vector3(n, 0, 0)) for n in (10, 2, 1)}

    ids = [d["id"] for d in build_state_message(readings, now_s=0.0)["drones"]]

    assert ids == ["drone_1", "drone_2", "drone_10"]


def test_a_mission_is_complete_only_when_every_assigned_drone_finished_and_disarmed():
    done = DroneReadings(Vector3(0, 0, 0), 0.0, armed=False, mission_id=MISSION, complete=True)
    flying = DroneReadings(Vector3(0, 0, 5), 0.0, armed=True, mission_id=MISSION, complete=True)
    other = DroneReadings(Vector3(0, 0, 0), 0.0, armed=False, mission_id="old", complete=True)

    assert mission_complete({"drone_1": done, "drone_2": done}, MISSION, ["drone_1", "drone_2"])
    assert not mission_complete(
        {"drone_1": done, "drone_2": flying}, MISSION, ["drone_1", "drone_2"]
    )
    assert not mission_complete(
        {"drone_1": done, "drone_2": other}, MISSION, ["drone_1", "drone_2"]
    )
    assert not mission_complete({"drone_1": done}, MISSION, ["drone_1", "drone_2"])
    assert not mission_complete({"drone_1": done}, MISSION, [])


def test_waypoint_progress_is_only_reported_for_the_current_mission():
    readings = {
        "drone_1": DroneReadings(
            Vector3(0, 0, 5), 0.0, mission_id="old", waypoint_index=1, waypoint_count=2
        )
    }

    drone = build_state_message(readings, 0.0, mission_id=MISSION, mission_drones=["drone_1"])[
        "drones"
    ][0]

    assert drone["waypoint_index"] is None and drone["waypoint_count"] is None


def test_positions_are_plain_floats():
    readings = {"drone_1": DroneReadings(position_world=Vector3(math.pi, 0.0, 1.0))}

    drone = build_state_message(readings, 0.0)["drones"][0]

    assert drone["x"] == pytest.approx(math.pi)
