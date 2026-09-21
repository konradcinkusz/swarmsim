import pytest

from swarm_coordination.scenarios import Scenario, Verdict
from swarm_coordination.scenarios.battery_reallocation import (
    _BATTERY_THRESHOLD_PCT,
    SCENARIO,
    _Drone,
    _run,
    reallocate_low_battery_tasks,
)


def test_scenario_exposes_the_contract_fields():
    assert isinstance(SCENARIO, Scenario)
    assert SCENARIO.name == "battery_reallocation"
    assert SCENARIO.description
    assert callable(SCENARIO.run)


def test_scenario_passes_with_its_default_fleet():
    # SCENARIO.run()'s default fleet has one low-battery drone and one idle,
    # above-threshold replacement, so reallocation should succeed.
    verdict = SCENARIO.run()
    assert verdict == Verdict(passed=True, violations=[])


def test_reallocate_moves_task_to_an_available_drone():
    drones = [
        _Drone("drone_1", battery_pct=10.0, task_id="patrol_north"),
        _Drone("drone_2", battery_pct=80.0, task_id=None),
    ]
    result = reallocate_low_battery_tasks(drones)
    by_id = {drone.drone_id: drone for drone in result}
    assert by_id["drone_1"].task_id is None
    assert by_id["drone_2"].task_id == "patrol_north"


def test_reallocate_is_a_noop_when_no_drone_is_below_threshold():
    drones = [
        _Drone("drone_1", battery_pct=90.0, task_id="patrol_north"),
        _Drone("drone_2", battery_pct=80.0, task_id=None),
    ]
    assert reallocate_low_battery_tasks(drones) == drones


def test_reallocate_never_hands_a_task_to_a_replacement_below_threshold():
    # drone_2 is idle but itself under threshold, so it must not be picked.
    drones = [
        _Drone("drone_1", battery_pct=10.0, task_id="patrol_north"),
        _Drone("drone_2", battery_pct=5.0, task_id=None),
    ]
    result = reallocate_low_battery_tasks(drones)
    by_id = {drone.drone_id: drone for drone in result}
    assert by_id["drone_1"].task_id == "patrol_north"
    assert by_id["drone_2"].task_id is None


def test_run_passes_when_a_replacement_drone_is_available():
    drones = [
        _Drone("drone_1", battery_pct=12.0, task_id="patrol_north"),
        _Drone("drone_2", battery_pct=85.0, task_id=None),
    ]
    verdict = _run(drones, timestamp_s=12.0)
    assert verdict == Verdict(passed=True, violations=[])


def test_run_reports_a_violation_when_no_replacement_is_available():
    # drone_2 is healthy but already busy with its own task, so it cannot take over
    # drone_1's; drone_1 is left flying its task on a depleted battery.
    drones = [
        _Drone("drone_1", battery_pct=8.0, task_id="patrol_north"),
        _Drone("drone_2", battery_pct=90.0, task_id="patrol_south"),
    ]
    verdict = _run(drones, timestamp_s=99.0)

    assert verdict.passed is False
    assert len(verdict.violations) == 1

    violation = verdict.violations[0]
    assert violation.drone_ids == ["drone_1"]
    assert violation.timestamp_s == pytest.approx(99.0)
    assert violation.measured_value == pytest.approx(8.0)
    assert violation.threshold == pytest.approx(_BATTERY_THRESHOLD_PCT)
    assert "drone_1" in violation.description
    assert "patrol_north" in violation.description


def test_run_uses_a_custom_threshold():
    drones = [_Drone("drone_1", battery_pct=25.0, task_id="patrol_north")]
    verdict = _run(drones, threshold_pct=30.0, timestamp_s=5.0)

    assert verdict.passed is False
    violation = verdict.violations[0]
    assert violation.threshold == pytest.approx(30.0)
    assert violation.measured_value == pytest.approx(25.0)
    assert violation.timestamp_s == pytest.approx(5.0)


def test_run_reports_a_violation_per_stuck_drone():
    drones = [
        _Drone("drone_1", battery_pct=5.0, task_id="patrol_north"),
        _Drone("drone_2", battery_pct=10.0, task_id="patrol_south"),
    ]
    verdict = _run(drones, timestamp_s=1.0)

    assert verdict.passed is False
    assert {violation.drone_ids[0] for violation in verdict.violations} == {
        "drone_1",
        "drone_2",
    }
