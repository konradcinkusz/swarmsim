from swarm_coordination.scenarios import Scenario, Verdict, Violation
from swarm_coordination.scenarios.example_static_formation import SCENARIO


def test_example_scenario_exposes_the_contract_fields():
    assert isinstance(SCENARIO, Scenario)
    assert SCENARIO.name == "static_formation_holds"
    assert SCENARIO.description
    assert callable(SCENARIO.run)


def test_example_scenario_passes_with_no_violations():
    verdict = SCENARIO.run()
    assert verdict == Verdict(passed=True, violations=[])


def _run_toy_failing_scenario() -> Verdict:
    """A hand-written scenario that always fails, to prove Verdict/Violation reporting."""
    violation = Violation(
        drone_ids=["drone_1", "drone_2"],
        timestamp_s=3.5,
        measured_value=0.3,
        threshold=1.0,
        description="drone_1 and drone_2 came within 0.3m of each other",
    )
    return Verdict(passed=False, violations=[violation])


def test_toy_scenario_reports_a_failing_verdict_with_its_violation():
    toy_scenario = Scenario(
        name="toy_always_fails",
        description="Hand-written scenario that deliberately fails, for contract tests.",
        run=_run_toy_failing_scenario,
    )

    verdict = toy_scenario.run()

    assert verdict.passed is False
    assert len(verdict.violations) == 1

    violation = verdict.violations[0]
    assert violation.drone_ids == ["drone_1", "drone_2"]
    assert violation.timestamp_s == 3.5
    assert violation.measured_value == 0.3
    assert violation.threshold == 1.0
    assert violation.description == "drone_1 and drone_2 came within 0.3m of each other"


def test_violation_and_verdict_are_plain_comparable_dataclasses():
    violation_a = Violation(
        drone_ids=["drone_1"],
        timestamp_s=1.0,
        measured_value=0.5,
        threshold=1.0,
        description="too close",
    )
    violation_b = Violation(
        drone_ids=["drone_1"],
        timestamp_s=1.0,
        measured_value=0.5,
        threshold=1.0,
        description="too close",
    )
    assert violation_a == violation_b
    assert Verdict(passed=False, violations=[violation_a]) == Verdict(
        passed=False, violations=[violation_b]
    )


def test_verdict_defaults_to_no_violations():
    assert Verdict(passed=True).violations == []
