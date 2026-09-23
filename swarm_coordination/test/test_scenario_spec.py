"""Scenario files are data: the schema and the loader refuse what cannot be run."""

import copy
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("yaml")

from swarm_coordination.scenarios.spec import (  # noqa: E402
    ScenarioError,
    discover,
    load_scenario,
    parse_scenario,
)
from swarm_coordination.trajectory import Vector3  # noqa: E402

SCENARIOS = Path(__file__).resolve().parents[2] / "scenarios"

MINIMAL = {
    "version": 1,
    "name": "minimal",
    "description": "One drone, one waypoint.",
    "drones": 2,
    "duration_s": 30,
    "events": [
        {
            "at_s": 1,
            "mission": {
                "type": "waypoint",
                "waypoints": [[0, 0, 5]],
                "drone_count": 1,
                "spacing_m": 3,
            },
        }
    ],
    "assertions": [{"all_landed": {"by_s": 30}}],
}


def _with(**changes):
    document = copy.deepcopy(MINIMAL)
    document.update(changes)
    return document


def test_every_scenario_in_the_repository_loads():
    files = discover([SCENARIOS])

    assert len(files) >= 10
    for path in files:
        spec = load_scenario(path)
        assert spec.name == path.stem, f"{path}: name and file name differ"


def test_a_minimal_scenario_gets_the_documented_defaults():
    spec = parse_scenario(MINIMAL)

    assert spec.expect == "pass"
    assert spec.initial_battery_pct == 100.0
    assert spec.world.gps_noise_std_m == 0.0
    assert spec.home("drone_2") == Vector3(0.0, 3.0, 0.0)  # simulation/px4-configs pads
    assert spec.drone_ids == ["drone_1", "drone_2"]


def test_events_are_run_in_time_order_whatever_order_they_are_written_in():
    document = _with(
        events=[
            {"at_s": 9, "command": "land"},
            *MINIMAL["events"],
            {"at_s": 4, "battery": {"drone": "drone_1", "set_pct": 30}},
        ]
    )

    assert [e.at_s for e in parse_scenario(document).events] == [1, 4, 9]


@pytest.mark.parametrize(
    ("document", "complaint"),
    [
        (_with(version=2), "version"),
        (_with(name="Not Snake Case"), "name"),
        (_with(drones=0), "drones"),
        (_with(events=[]), "events"),
        (_with(assertions=[{"teleports": {}}]), "assertions/0"),
        (_with(assertions=[{"all_landed": {}}]), "by_s"),
        (_with(events=[{"at_s": 1, "command": "dance"}]), "events/0"),
        (_with(events=[{"at_s": 1, "command": "land", "mission": {}}]), "events/0"),
        (_with(surprise=True), "surprise"),
    ],
)
def test_the_schema_refuses_malformed_scenarios_and_says_where(document, complaint):
    with pytest.raises(ScenarioError, match=complaint):
        parse_scenario(document)


def test_a_drone_the_scenario_does_not_have_is_refused():
    document = _with(events=[{"at_s": 1, "battery": {"drone": "drone_9", "set_pct": 10}}])

    with pytest.raises(ScenarioError, match="drone_9 does not exist"):
        parse_scenario(document)


def test_a_mission_needing_more_drones_than_the_scenario_has_is_refused():
    document = copy.deepcopy(MINIMAL)
    document["events"][0]["mission"]["drone_count"] = 5

    with pytest.raises(ScenarioError, match="needs 5 drone"):
        parse_scenario(document)


def test_an_expected_failure_must_say_why():
    with pytest.raises(ScenarioError, match="expect_reason"):
        parse_scenario(_with(expect="fail"))


def test_unreadable_files_and_missing_paths_are_scenario_errors(tmp_path):
    broken = tmp_path / "broken.yaml"
    broken.write_text("version: [1,", encoding="utf-8")
    listed = tmp_path / "listed.yaml"
    listed.write_text("- just\n- a list\n", encoding="utf-8")

    with pytest.raises(ScenarioError, match="broken.yaml"):
        load_scenario(broken)
    with pytest.raises(ScenarioError, match="mapping"):
        load_scenario(listed)
    with pytest.raises(ScenarioError, match="no such file"):
        discover([tmp_path / "nowhere"])
