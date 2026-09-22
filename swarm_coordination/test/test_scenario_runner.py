"""The harness, the suite runner and the command line, end to end."""

import copy
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

jsonschema = pytest.importorskip("jsonschema")
pytest.importorskip("yaml")

from swarm_coordination.scenarios import runner  # noqa: E402
from swarm_coordination.scenarios.__main__ import main  # noqa: E402
from swarm_coordination.scenarios.harness import mission_payload, run_scenario  # noqa: E402
from swarm_coordination.scenarios.mutants import MUTANTS, Mutant  # noqa: E402
from swarm_coordination.scenarios.spec import load_scenario, parse_scenario  # noqa: E402
from swarm_coordination.scenarios.sut import ReferenceSwarm  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scenarios"
ROSBRIDGE = ROOT / "contracts" / "rosbridge"


def _schema(name):
    return json.loads((ROSBRIDGE / name).read_text(encoding="utf-8"))


def test_the_same_seed_reproduces_a_run_exactly_and_another_seed_does_not():
    spec = load_scenario(SCENARIOS / "formation_line_in_wind.yaml")

    first = run_scenario(spec, ReferenceSwarm(), seed=4)[1].as_dict()
    again = run_scenario(spec, ReferenceSwarm(), seed=4)[1].as_dict()
    other = run_scenario(spec, ReferenceSwarm(), seed=5)[1].as_dict()

    assert first == again
    assert first["drones"] != other["drones"]


def test_the_swarm_is_driven_through_the_rosbridge_contract():
    spec = load_scenario(SCENARIOS / "low_battery_handover.yaml")
    mission = next(e for e in spec.events if e.kind == "mission")

    payload = mission_payload(spec, 0, mission.data, seed=1)
    jsonschema.validate(payload, _schema("swarm_mission.v1.schema.json"))

    swarm = ReferenceSwarm()
    fleet_ground = swarm.ground([])
    report = fleet_ground.report()
    jsonschema.validate(report, _schema("swarm_state.v1.schema.json"))


def test_a_state_report_mid_flight_matches_the_state_contract():
    spec = load_scenario(SCENARIOS / "waypoint_lanes.yaml")
    captured = {}

    class Recording(ReferenceSwarm):
        def ground(self, fleet):
            ground = super().ground(fleet)
            captured["ground"] = ground
            return ground

    run_scenario(spec, Recording(), seed=1)
    report = captured["ground"].report()

    def plain(value):  # positions travel as Vector3 inside the harness
        if hasattr(value, "x"):
            return [value.x, value.y, value.z]
        return value

    assert len(report["drones"]) == 3
    assert report["mission"]["complete"] is True
    jsonschema.validate(
        json.loads(json.dumps(report, default=plain)), _schema("swarm_state.v1.schema.json")
    )


def test_a_comms_loss_cuts_messages_both_ways_for_its_duration_only():
    spec = load_scenario(SCENARIOS / "follower_comms_blip.yaml")
    heard = []

    class Listening(ReferenceSwarm):
        def drone(self, drone, fleet):
            software = super().drone(drone, fleet)
            if drone.drone_id == "drone_3":
                original = software.step

                def step(now, observation, inbox):
                    heard.append((now, len(inbox)))
                    return original(now, observation, inbox)

                software.step = step
            return software

    run_scenario(spec, Listening(), seed=1)

    silent = [t for t, count in heard if count == 0 and t > 2]
    assert silent and min(silent) >= 25.0 and max(silent) < 28.2


def _suite(tmp_path, *documents):
    for document in documents:
        (tmp_path / f"{document['name']}.yaml").write_text(json.dumps(document), encoding="utf-8")
    return tmp_path


BASE = {
    "version": 1,
    "name": "short_hop",
    "description": "Two drones hop 10 m.",
    "drones": 2,
    "duration_s": 40,
    "events": [
        {
            "at_s": 1,
            "mission": {
                "type": "waypoint",
                "waypoints": [[0, 0, 5], [10, 0, 5]],
                "drone_count": 2,
                "spacing_m": 3,
            },
        }
    ],
    "assertions": [{"mission_completes": {"within_s": 35}}],
}


def _variant(name, **changes):
    document = copy.deepcopy(BASE)
    document.update(name=name, **changes)
    return document


def test_expected_failures_are_reported_as_xfail_and_surprise_passes_as_xpass(tmp_path):
    suite = _suite(
        tmp_path,
        _variant(
            "known_gap",
            expect="fail",
            expect_reason="documented",
            assertions=[{"mission_completes": {"within_s": 2}}],
        ),
        _variant("gap_closed", expect="fail", expect_reason="documented"),
    )

    report = runner.run_suite([suite], ReferenceSwarm(), [1])

    outcomes = {s.spec.name: s.outcome for s in report.scenarios}
    assert outcomes == {"known_gap": "xfail", "gap_closed": "xpass"}
    assert not report.ok  # an xpass means the written-down limitation is out of date


def test_a_scenario_no_mutant_fails_is_toothless_and_fails_the_suite(tmp_path, monkeypatch):
    suite = _suite(tmp_path, _variant("easy", assertions=[{"all_landed": {"by_s": 40}}]))
    harmless = Mutant("harmless", "changes nothing", ReferenceSwarm(name="mutant:harmless"))
    monkeypatch.setattr(runner, "MUTANTS", (harmless,))

    report = runner.run_suite([suite], ReferenceSwarm(), [1], mutation=True)

    assert report.scenarios[0].toothless
    assert report.survivors() == ["harmless"]
    assert not report.ok


def test_duplicate_names_and_broken_files_are_errors_not_crashes(tmp_path):
    (tmp_path / "a.yaml").write_text(json.dumps(BASE), encoding="utf-8")
    (tmp_path / "b.yaml").write_text(json.dumps(BASE), encoding="utf-8")
    (tmp_path / "c.yaml").write_text("version: 1\n", encoding="utf-8")

    report = runner.run_suite([tmp_path], ReferenceSwarm(), [1])

    assert any("used twice" in e for e in report.errors)
    assert any("c.yaml" in e for e in report.errors)
    assert not report.ok


def test_the_repository_suite_passes_and_every_scenario_catches_a_mutant():
    report = runner.run_suite([SCENARIOS], ReferenceSwarm(), [1], mutation=True)

    assert report.ok, runner.to_markdown(report)
    assert {s.outcome for s in report.scenarios} <= {"passed", "xfail"}
    assert not report.survivors()
    assert len(report.mutants) == len(MUTANTS)


def test_junit_and_json_reports_describe_the_same_run(tmp_path):
    report = runner.run_suite(
        [FIXTURES, SCENARIOS / "waypoint_lanes.yaml"], ReferenceSwarm(), [1, 2]
    )

    junit = ElementTree.fromstring(runner.to_junit(report))
    document = runner.to_json(report)

    assert junit.get("tests") == "4" and junit.get("failures") == "2"
    failure = junit.find(".//testcase[@classname='scenarios.impossible_deadline']/failure")
    assert "reported complete after" in failure.get("message")
    assert document["ok"] is False
    assert document["counts"] == {"passed": 1, "failed": 1, "xfail": 0, "xpass": 0}
    runs = next(s for s in document["scenarios"] if s["name"] == "impossible_deadline")["runs"]
    assert runs[0]["assertions"][0]["violations"][0]["threshold"] == 5.0


def test_the_command_line_exit_status_follows_the_outcome(tmp_path, capsys):
    junit = tmp_path / "out" / "results.xml"
    summary = tmp_path / "summary.md"

    assert main(["run", str(SCENARIOS / "waypoint_lanes.yaml"), "--junit", str(junit)]) == 0
    assert main(["run", str(FIXTURES), "--markdown", str(summary)]) == 1
    assert main(["run", str(tmp_path / "missing")]) == 2
    assert main(["validate", str(SCENARIOS)]) == 0
    assert main(["mutants"]) == 0

    assert ElementTree.parse(junit).getroot().get("failures") == "0"
    assert "impossible_deadline" in summary.read_text(encoding="utf-8")
    assert "never_lands" in capsys.readouterr().out


def test_another_swarm_plugs_in_with_sut(tmp_path, monkeypatch):
    (tmp_path / "my_swarm.py").write_text(
        "from swarm_coordination.scenarios.sut import ReferenceSwarm\n"
        "def build():\n"
        "    return ReferenceSwarm(name='my-swarm')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "report.json"

    status = main(
        [
            "run",
            str(SCENARIOS / "waypoint_lanes.yaml"),
            "--sut",
            "my_swarm:build",
            "--json",
            str(output),
        ]
    )

    assert status == 0
    assert json.loads(output.read_text(encoding="utf-8"))["sut"] == "my-swarm"
    assert main(["run", str(SCENARIOS), "--sut", "my_swarm:build", "--mutants"]) == 2
    assert main(["run", str(SCENARIOS), "--sut", "my_swarm:nothing"]) == 2


def test_parse_scenario_accepts_what_the_yaml_loader_produces():
    spec = parse_scenario(copy.deepcopy(BASE))

    assert spec.name == "short_hop" and spec.events[0].kind == "mission"
