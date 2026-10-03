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
from swarm_coordination.scenarios.expectations import (  # noqa: E402
    Expectations,
    load_expectations,
)
from swarm_coordination.scenarios.harness import mission_payload, run_scenario  # noqa: E402
from swarm_coordination.scenarios.mutants import MUTANTS, Mutant  # noqa: E402
from swarm_coordination.scenarios.spec import load_scenario, parse_scenario  # noqa: E402
from swarm_coordination.scenarios.sut import ReferenceSwarm  # noqa: E402
from swarm_coordination.supervisor import MissionSupervisor  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scenarios"
EXPECTATION_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "expectations"
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


def test_follower_comms_blip_measures_the_recovered_formation_and_catches_a_wrong_frame():
    """Its formation check started at 40 s, after the formation had landed (37 s). It
    measured nothing, passed whatever drone_3 did, and let no_frame_conversion through."""
    spec = load_scenario(SCENARIOS / "follower_comms_blip.yaml")

    verdict, _ = run_scenario(spec, ReferenceSwarm(), 1)
    outcome = next(o for o in verdict.outcomes if o.assertion == "formation_error")
    assert outcome.passed and outcome.measured == pytest.approx(2.277, abs=0.01)

    mutant = next(m for m in MUTANTS if m.name == "no_frame_conversion")
    broken, _ = run_scenario(spec, mutant.sut, 1)
    assert "formation_error" in {o.assertion for o in broken.outcomes if not o.passed}


class _SecondDroneLeads(MissionSupervisor):
    """Elects drone_2 and gives drone_1 the first slot: not the reference swarm's roles."""

    def __init__(self, drones, battery_threshold_pct=20.0):
        super().__init__(drones, battery_threshold_pct)
        self.drones = [self.drones[1], self.drones[0], *self.drones[2:]]


def test_formation_error_judges_the_shape_not_the_reference_swarms_roles():
    """A swarm that elects drone_2 flies the same line. formation_error used to assume that
    drone_1 leads and the others take the slots in id order, and measured this swarm 8.2 m
    out of formation (limit 2.5 m)."""
    spec = load_scenario(SCENARIOS / "formation_line.yaml")
    swarm = ReferenceSwarm(name="second-leads", supervisor_cls=_SecondDroneLeads)

    verdict, trace = run_scenario(spec, swarm, 1)

    outcome = next(o for o in verdict.outcomes if o.assertion == "formation_error")
    assert outcome.passed and outcome.measured == pytest.approx(2.2, abs=0.05)
    # The roles really were not the reference swarm's: in mid-flight drone_2 is in front.
    frame = next(f for f in trace.frames if f.t_s >= 22.0)
    assert {s.mode for s in frame.drones} == {"OFFBOARD"}
    assert max(frame.drones, key=lambda s: s.position.x).drone_id == "drone_2"


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


def _one_gap_closed_and_one_of_its_own(directory):
    """Flown by the reference swarm as if it were another swarm: it passes a scenario whose
    file says the reference fails it, and fails one whose file says nothing."""
    directory.mkdir(exist_ok=True)
    return _suite(
        directory,
        _variant("reference_gap", expect="fail", expect_reason="the reference cannot do this"),
        _variant("own_gap", assertions=[{"mission_completes": {"within_s": 2}}]),
    )


def test_a_swarms_expectations_replace_the_scenario_files_own(tmp_path):
    suite = _one_gap_closed_and_one_of_its_own(tmp_path)
    expectations = Expectations({"own_gap": "too slow for a 2 s deadline"}, source="mine.yaml")

    by_the_files = runner.run_suite([suite], ReferenceSwarm(), [1])
    by_the_swarm = runner.run_suite([suite], ReferenceSwarm(), [1], expectations=expectations)

    assert {s.spec.name: s.outcome for s in by_the_files.scenarios} == {
        "reference_gap": "xpass",  # a gap that is closed, held against this swarm
        "own_gap": "failed",  # a gap nobody wrote down
    }
    assert not by_the_files.ok
    assert {s.spec.name: s.outcome for s in by_the_swarm.scenarios} == {
        "reference_gap": "passed",  # the reference's declaration is not this swarm's
        "own_gap": "xfail",
    }
    assert by_the_swarm.ok


def test_the_reports_carry_the_expectation_that_applied(tmp_path):
    suite = _one_gap_closed_and_one_of_its_own(tmp_path)
    schema = json.loads((ROOT / "contracts" / "scenario" / "report.v1.schema.json").read_text())
    expectations = Expectations({"own_gap": "too slow for a 2 s deadline"}, source="mine.yaml")

    report = runner.run_suite([suite], ReferenceSwarm(), [1], expectations=expectations)

    document = runner.to_json(report)
    jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)  # still v1
    by_name = {s["name"]: s for s in document["scenarios"]}
    assert (by_name["own_gap"]["expect"], by_name["own_gap"]["expect_reason"]) == (
        "fail",
        "too slow for a 2 s deadline",
    )
    assert (by_name["reference_gap"]["expect"], by_name["reference_gap"]["expect_reason"]) == (
        "pass",
        None,
    )
    markdown = runner.to_markdown(report)
    assert "Expectations from `mine.yaml`" in markdown
    assert "too slow for a 2 s deadline" in markdown
    assert "the reference cannot do this" not in markdown
    junit = ElementTree.fromstring(runner.to_junit(report))
    skipped = junit.find(".//testcase[@classname='scenarios.own_gap']/skipped")
    assert skipped.get("message") == "expected failure: too slow for a 2 s deadline"
    assert junit.get("failures") == "0"


def test_a_surprise_pass_says_it_was_expected_to_fail_whoever_expected_it(tmp_path):
    suite = _suite(tmp_path, _variant("gap_closed"))
    expectations = Expectations({"gap_closed": "this swarm cannot do it"})

    report = runner.run_suite([suite], ReferenceSwarm(), [1], expectations=expectations)

    assert report.scenarios[0].outcome == "xpass" and not report.ok
    junit = ElementTree.fromstring(runner.to_junit(report))
    failure = junit.find(".//testcase[@classname='scenarios.gap_closed']/failure")
    assert failure.get("message") == "passed, but it is expected to fail"
    assert "this swarm cannot do it" in failure.text


def test_a_name_that_matches_no_scenario_is_reported_and_does_not_fail_the_run(tmp_path):
    suite = _one_gap_closed_and_one_of_its_own(tmp_path)
    expectations = Expectations(
        {"own_gap": "too slow", "own_gapp": "a typo", "removed_long_ago": "stale"},
        source="mine.yaml",
    )

    report = runner.run_suite([suite], ReferenceSwarm(), [1], expectations=expectations)

    assert report.unused_expectations() == ["own_gapp", "removed_long_ago"]
    assert report.ok
    assert "`own_gapp`, `removed_long_ago`" in runner.to_markdown(report)
    without = runner.run_suite([suite], ReferenceSwarm(), [1])
    assert "not in this run" not in runner.to_markdown(without)


def test_an_expectations_file_among_the_scenarios_is_not_one_of_them(tmp_path):
    suite = _one_gap_closed_and_one_of_its_own(tmp_path)
    mine = tmp_path / "expectations.yaml"
    mine.write_text("version: 1\nexpect_fail:\n  own_gap: too slow\n", encoding="utf-8")

    report = runner.run_suite([suite], ReferenceSwarm(), [1], expectations=load_expectations(mine))

    assert report.ok and not report.errors
    assert sorted(s.spec.name for s in report.scenarios) == ["own_gap", "reference_gap"]


def test_the_mutation_check_follows_the_expectations_too(tmp_path, monkeypatch):
    suite = _one_gap_closed_and_one_of_its_own(tmp_path)
    harmless = Mutant("harmless", "changes nothing", ReferenceSwarm(name="mutant:harmless"))
    monkeypatch.setattr(runner, "MUTANTS", (harmless,))
    expectations = Expectations({"own_gap": "too slow"})

    report = runner.run_suite(
        [suite], ReferenceSwarm(), [1], mutation=True, expectations=expectations
    )

    # An expected failure says nothing by failing a mutant. What this swarm passes must.
    assert {s.spec.name: s.killed_by for s in report.scenarios} == {
        "own_gap": None,
        "reference_gap": [],
    }
    assert [s.spec.name for s in report.scenarios if s.toothless] == ["reference_gap"]


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


def test_the_json_report_is_the_report_contract_and_the_example_is_current(tmp_path):
    schema = json.loads((ROOT / "contracts" / "scenario" / "report.v1.schema.json").read_text())
    example = json.loads((ROOT / "contracts" / "scenario" / "examples" / "report.json").read_text())
    report = runner.run_suite(
        [SCENARIOS / "waypoint_lanes.yaml", SCENARIOS / "v_formation_from_pads.yaml"],
        ReferenceSwarm(),
        [1, 2],
        mutation=True,
    )

    document = runner.to_json(report)

    jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)
    jsonschema.validate(example, schema, cls=jsonschema.Draft202012Validator)
    # The example SwarmApi.Api's tests ingest is what this runner writes today, not a
    # hand-edited file: same scenarios, outcomes and measurements.
    assert _without_wall_times(document) == _without_wall_times(example)


def _without_wall_times(document: dict) -> dict:
    document = copy.deepcopy(document)
    for scenario in document["scenarios"]:
        scenario["source"] = Path(scenario["source"]).name if scenario["source"] else None
        for run in scenario["runs"]:
            run.pop("wall_time_s")
    return document


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


def test_the_command_line_takes_the_expectations_of_the_swarm_under_test(tmp_path, capsys):
    suite = _one_gap_closed_and_one_of_its_own(tmp_path / "suite")
    mine = tmp_path / "mine.yaml"
    mine.write_text("version: 1\nexpect_fail:\n  own_gap: too slow\n", encoding="utf-8")
    report = tmp_path / "report.json"

    assert main(["run", str(suite)]) == 1  # the files' own: a closed gap is a surprise
    assert main(["run", str(suite), "--expect", str(mine), "--json", str(report)]) == 0
    assert main(["run", str(suite), "--expect", str(EXPECTATION_FIXTURES / "all_pass.yaml")]) == 1

    scenarios = {s["name"]: s for s in json.loads(report.read_text(encoding="utf-8"))["scenarios"]}
    assert scenarios["own_gap"]["outcome"] == "xfail"
    assert scenarios["reference_gap"]["outcome"] == "passed"
    assert "Expectations from" in capsys.readouterr().out


def test_expectations_that_cannot_be_used_are_exit_status_2_with_the_reason(tmp_path, capsys):
    suite = _one_gap_closed_and_one_of_its_own(tmp_path / "suite")
    wrong = tmp_path / "wrong.yaml"
    wrong.write_text("version: 2\n", encoding="utf-8")

    assert main(["run", str(suite), "--expect", str(wrong)]) == 2
    assert main(["run", str(suite), "--expect", str(tmp_path / "missing.yaml")]) == 2

    error = capsys.readouterr().err
    assert "wrong.yaml: version: 1 was expected" in error and "missing.yaml" in error


def test_the_fixtures_the_ci_check_uses_behave_as_that_check_expects():
    gap = str(SCENARIOS / "v_formation_from_pads.yaml")
    # The reference swarm's known gap, with nothing excused: the file does not inherit it.
    assert main(["run", gap]) == 0
    assert main(["run", gap, "--expect", str(EXPECTATION_FIXTURES / "all_pass.yaml")]) == 1
    # A failing scenario whose failure the file writes down: recorded, not hidden.
    assert main(["run", str(FIXTURES)]) == 1
    assert (
        main(
            [
                "run",
                str(FIXTURES),
                "--expect",
                str(EXPECTATION_FIXTURES / "impossible_deadline.yaml"),
            ]
        )
        == 0
    )


def test_parse_scenario_accepts_what_the_yaml_loader_produces():
    spec = parse_scenario(copy.deepcopy(BASE))

    assert spec.name == "short_hop" and spec.events[0].kind == "mission"
