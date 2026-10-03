"""Expectations files: what one swarm is expected to fail, read and applied to scenarios."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
yaml = pytest.importorskip("yaml")

from swarm_coordination.scenarios.expectations import (  # noqa: E402
    EXPECTATIONS_SCHEMA_NAME,
    Expectations,
    load_expectations,
    parse_expectations,
)
from swarm_coordination.scenarios.spec import (  # noqa: E402
    SCHEMA_NAME,
    ScenarioError,
    load_scenario,
    schema_text,
)

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios"
EXAMPLE = ROOT / "contracts" / "scenario" / "examples" / "expectations.yaml"


def test_the_contract_example_is_valid_and_names_scenarios_that_exist():
    document = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    schema = json.loads(schema_text(EXPECTATIONS_SCHEMA_NAME))

    jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)
    expectations = load_expectations(EXAMPLE)

    assert expectations.expect_fail
    assert set(expectations.expect_fail) <= {p.stem for p in SCENARIOS.glob("*.yaml")}


def test_a_file_with_only_a_version_expects_every_scenario_to_pass():
    assert parse_expectations({"version": 1}).expect_fail == {}


def test_a_reason_folded_over_several_lines_is_kept_as_one():
    expectations = parse_expectations(
        {"version": 1, "expect_fail": {"known_gap": "Folded\n  over\n  lines.\n"}}
    )

    assert expectations.expect_fail == {"known_gap": "Folded over lines."}


@pytest.mark.parametrize(
    ("document", "complaint"),
    [
        ({"expect_fail": {"known_gap": "documented"}}, "'version' is a required property"),
        ({"version": 2}, "version: 1 was expected"),
        ({"version": 1, "expect_fails": {}}, "'expect_fails' was unexpected"),
        ({"version": 1, "expect_fail": ["known_gap"]}, "expect_fail: .* is not of type 'object'"),
        ({"version": 1, "expect_fail": {"known_gap": None}}, "expect_fail/known_gap: None is not"),
        ({"version": 1, "expect_fail": {"known_gap": ""}}, "expect_fail/known_gap: ''"),
        (
            {"version": 1, "expect_fail": {"known_gap": " \n "}},
            "known_gap needs a reason saying why",
        ),
        ({"version": 1, "expect_fail": {"Known Gap": "documented"}}, "'Known Gap' does not match"),
        ({"version": 1, "expect_fail": {7: "documented"}}, "7 is not of type 'string'"),
    ],
)
def test_the_schema_refuses_malformed_expectations_and_says_where(document, complaint):
    with pytest.raises(ScenarioError, match=complaint) as refused:
        parse_expectations(document, source="lab.yaml")

    assert str(refused.value).startswith("lab.yaml: ")


def test_a_file_that_cannot_be_read_is_an_error_that_names_it(tmp_path):
    broken = tmp_path / "broken.yaml"
    broken.write_text("version: [1\n", encoding="utf-8")
    listed = tmp_path / "listed.yaml"
    listed.write_text("- version: 1\n", encoding="utf-8")
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")

    with pytest.raises(ScenarioError, match="broken.yaml"):
        load_expectations(broken)
    with pytest.raises(
        ScenarioError, match="listed.yaml: an expectations file must hold a mapping"
    ):
        load_expectations(listed)
    with pytest.raises(ScenarioError, match="empty.yaml: an expectations file must hold a mapping"):
        load_expectations(empty)
    with pytest.raises(ScenarioError, match="missing.yaml"):
        load_expectations(tmp_path / "missing.yaml")


def test_the_names_the_schema_accepts_are_the_names_scenario_files_accept():
    scenario = json.loads(schema_text(SCHEMA_NAME))["properties"]["name"]["pattern"]
    expectations = json.loads(schema_text(EXPECTATIONS_SCHEMA_NAME))["properties"]["expect_fail"]

    assert expectations["propertyNames"]["pattern"] == scenario


def test_apply_puts_this_swarms_expectation_in_place_of_the_one_the_file_declares():
    gap = load_scenario(SCENARIOS / "v_formation_from_pads.yaml")  # the reference's known gap
    plain = load_scenario(SCENARIOS / "waypoint_lanes.yaml")
    assert (gap.expect, plain.expect) == ("fail", "pass")
    expectations = Expectations({"waypoint_lanes": "this swarm does not fly lanes"})

    excused = expectations.apply(plain)
    held = expectations.apply(gap)

    assert (excused.expect, excused.expect_reason) == ("fail", "this swarm does not fly lanes")
    assert (held.expect, held.expect_reason) == ("pass", None)  # the file's own is ignored
    # Only the expectation changed, and the scenario that was read is as it was.
    assert replace(excused, expect="pass", expect_reason=None) == plain
    assert replace(held, expect="fail", expect_reason=gap.expect_reason) == gap
    assert gap.expect == "fail" and gap.expect_reason


def test_unused_names_are_the_ones_no_scenario_carries_in_the_files_order():
    expectations = parse_expectations(
        {"version": 1, "expect_fail": {"zeta": "z", "alpha": "a", "present": "p"}}
    )

    assert expectations.unused(["present", "other"]) == ["zeta", "alpha"]
    assert expectations.unused(["zeta", "alpha", "present"]) == []
