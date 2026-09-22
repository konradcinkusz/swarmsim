"""The Python half of the rosbridge contract, checked against the same example files the
.NET side is (backend/tests/SwarmApi.Infrastructure.Tests/RosBridgeProtocolTests.cs)."""

import json
from pathlib import Path

import pytest

from swarm_coordination.mission_planning import (
    parse_command_payload,
    parse_mission_payload,
    plan_mission,
)
from swarm_coordination.swarm_state import DroneReadings, build_state_message
from swarm_coordination.trajectory import Vector3

jsonschema = pytest.importorskip("jsonschema")

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "rosbridge"
MISSION_ID = "3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c"


def _schema(name):
    return json.loads((CONTRACTS / f"{name}.v1.schema.json").read_text())


def _example(name):
    return (CONTRACTS / "examples" / f"{name}.json").read_text()


@pytest.mark.parametrize("name", ["swarm_mission", "swarm_command", "swarm_state"])
def test_every_example_satisfies_its_schema(name):
    schema = _schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(json.loads(_example(name)))


def test_the_mission_example_parses_and_plans_a_v_formation():
    mission = parse_mission_payload(_example("swarm_mission"))
    plan = plan_mission(mission)

    assert mission.mission_id == MISSION_ID
    assert (mission.mission_type, mission.formation, mission.drone_count) == ("formation", "v", 3)
    assert plan.paths == {"drone_1": [Vector3(0.0, 0.0, 5.0), Vector3(10.0, 0.0, 5.0)]}
    assert plan.followers == {
        "drone_2": ("drone_1", Vector3(-2.5, 2.5, 0.0)),
        "drone_3": ("drone_1", Vector3(-2.5, -2.5, 0.0)),
    }
    assert plan.drones == ["drone_1", "drone_2", "drone_3"]


def test_the_command_example_parses():
    command = parse_command_payload(_example("swarm_command"))

    assert (command.command, command.mission_id) == ("rtl", MISSION_ID)


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[1, 2]",
        json.dumps(
            {
                "version": 2,
                "mission_id": MISSION_ID,
                "type": "waypoint",
                "waypoints": [[0, 0, 5]],
                "drone_count": 1,
                "spacing_m": 2,
            }
        ),
        json.dumps(
            {
                "version": 1,
                "mission_id": "nope",
                "type": "waypoint",
                "waypoints": [[0, 0, 5]],
                "drone_count": 1,
                "spacing_m": 2,
            }
        ),
        json.dumps(
            {
                "version": 1,
                "mission_id": MISSION_ID,
                "type": "orbit",
                "waypoints": [[0, 0, 5]],
                "drone_count": 1,
                "spacing_m": 2,
            }
        ),
        json.dumps(
            {
                "version": 1,
                "mission_id": MISSION_ID,
                "type": "formation",
                "formation": "circle",
                "waypoints": [[0, 0, 5]],
                "drone_count": 2,
                "spacing_m": 2,
            }
        ),
        json.dumps(
            {
                "version": 1,
                "mission_id": MISSION_ID,
                "type": "waypoint",
                "drone_count": 1,
                "spacing_m": 2,
            }
        ),
        json.dumps(
            {
                "version": 1,
                "mission_id": MISSION_ID,
                "type": "waypoint",
                "waypoints": [5],
                "drone_count": 1,
                "spacing_m": 2,
            }
        ),
    ],
)
def test_a_malformed_mission_is_a_value_error(payload):
    with pytest.raises(ValueError):
        parse_mission_payload(payload)


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"version": 1, "command": "explode"}),
        json.dumps({"version": 1, "command": "rtl", "mission_id": "nope"}),
        json.dumps({"command": "rtl"}),
    ],
)
def test_a_malformed_command_is_a_value_error(payload):
    with pytest.raises(ValueError):
        parse_command_payload(payload)


def test_what_the_aggregator_builds_satisfies_the_state_schema():
    readings = {
        "drone_1": DroneReadings(
            position_world=Vector3(4.2, 0.1, 5.0),
            position_time_s=99.9,
            armed=True,
            mode="OFFBOARD",
            battery_pct=87.5,
            mission_id=MISSION_ID,
            waypoint_index=1,
            waypoint_count=2,
        ),
        "drone_2": DroneReadings(position_world=Vector3(1.7, 2.6, 4.9)),
    }

    message = build_state_message(readings, 100.0, MISSION_ID, ["drone_1", "drone_2"])

    jsonschema.Draft202012Validator(_schema("swarm_state")).validate(message)
