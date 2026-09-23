"""Assertions read a trace and measure; checked here against hand-built traces."""

import pytest

pytest.importorskip("jsonschema")

from swarm_coordination.scenarios import assertions  # noqa: E402
from swarm_coordination.scenarios.model import DroneSample, Frame, Trace  # noqa: E402
from swarm_coordination.trajectory import Vector3  # noqa: E402

HOMES = {"drone_1": Vector3(0.0, 0.0, 0.0), "drone_2": Vector3(0.0, 3.0, 0.0)}
MISSION = "3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c"


def _sample(drone, position, armed=True, mode="OFFBOARD", battery=90.0):
    return DroneSample(drone, position, armed, mode, battery, position.z > 0.05)


def _trace(frames, missions=()):
    trace = Trace("hand_built", "reference", 1, 0.1, dict(HOMES))
    trace.missions = list(missions)
    trace.frames = frames
    return trace


def _frame(t, one, two, complete=False, mission=MISSION):
    return Frame(t, (one, two), mission, complete)


def _check(kind, trace, **params):
    return assertions.ASSERTIONS[kind](None, trace, params)


def test_min_separation_reports_the_closest_approach_of_each_pair_and_when():
    trace = _trace(
        [
            _frame(1.0, _sample("drone_1", Vector3(0, 0, 5)), _sample("drone_2", Vector3(0, 3, 5))),
            _frame(
                2.0, _sample("drone_1", Vector3(0, 0, 5)), _sample("drone_2", Vector3(0, 0.8, 5))
            ),
            _frame(
                3.0, _sample("drone_1", Vector3(0, 0, 5)), _sample("drone_2", Vector3(0, 1.2, 5))
            ),
        ]
    )

    outcome = _check("min_separation", trace, min_m=1.0)

    assert not outcome.passed and outcome.measured == pytest.approx(0.8)
    (violation,) = outcome.violations
    assert violation.drone_ids == ("drone_1", "drone_2")
    assert (violation.timestamp_s, violation.threshold) == (2.0, 1.0)


def test_min_separation_ignores_drones_on_the_ground_and_frames_outside_the_window():
    trace = _trace(
        [
            _frame(
                1.0, _sample("drone_1", Vector3(0, 0, 0)), _sample("drone_2", Vector3(0, 0.1, 5))
            ),
            _frame(
                9.0, _sample("drone_1", Vector3(0, 0, 5)), _sample("drone_2", Vector3(0, 0.1, 5))
            ),
        ]
    )

    assert _check("min_separation", trace, min_m=1.0, to_s=5.0).passed


def test_mission_completes_measures_from_dispatch_to_the_first_complete_report():
    frames = [
        _frame(
            t, _sample("drone_1", Vector3(0, 0, 0)), _sample("drone_2", Vector3(0, 3, 0)), t >= 21
        )
        for t in (5.0, 20.0, 21.0, 30.0)
    ]
    trace = _trace(frames, missions=[(1.0, MISSION, {})])

    on_time = _check("mission_completes", trace, within_s=25)
    late = _check("mission_completes", trace, within_s=10)

    assert on_time.passed and on_time.measured == 20.0
    assert not late.passed and late.violations[0].measured_value == 20.0


def test_mission_completes_fails_when_a_different_mission_is_reported_complete():
    frames = [
        _frame(
            5.0,
            _sample("drone_1", Vector3(0, 0, 0)),
            _sample("drone_2", Vector3(0, 3, 0)),
            complete=True,
            mission="another",
        )
    ]
    trace = _trace(frames, missions=[(1.0, MISSION, {})])

    assert (
        "never reported complete"
        in _check("mission_completes", trace, within_s=60).violations[0].description
    )


def test_all_landed_names_every_drone_still_up():
    trace = _trace(
        [
            _frame(
                10.0,
                _sample("drone_1", Vector3(0, 0, 0), armed=False),
                _sample("drone_2", Vector3(0, 3, 4), mode="AUTO.LAND"),
            ),
        ]
    )

    outcome = _check("all_landed", trace, by_s=10)

    assert [v.drone_ids for v in outcome.violations] == [("drone_2",)]
    assert "AUTO.LAND" in outcome.violations[0].description


def test_all_landed_measures_since_when_everybody_has_been_down():
    down = _sample("drone_1", Vector3(0, 0, 0), armed=False)
    trace = _trace(
        [
            _frame(8.0, down, _sample("drone_2", Vector3(0, 3, 1))),
            _frame(9.0, down, _sample("drone_2", Vector3(0, 3, 0), armed=False)),
            _frame(10.0, down, _sample("drone_2", Vector3(0, 3, 0), armed=False)),
        ]
    )

    assert _check("all_landed", trace, by_s=10).measured == 9.0


def test_no_task_below_battery_allows_the_grace_period_and_no_longer():
    def frame(t, battery, mode="OFFBOARD"):
        return _frame(
            t,
            _sample("drone_1", Vector3(5, 0, 5), mode=mode, battery=battery),
            _sample("drone_2", Vector3(5, 3, 5)),
        )

    handed_over = _trace([frame(1, 19), frame(2, 19), frame(3, 19, mode="AUTO.RTL")])
    kept_flying = _trace([frame(t, 19) for t in range(1, 8)])

    assert _check("no_task_below_battery", handed_over, threshold_pct=20, grace_s=3).passed
    outcome = _check("no_task_below_battery", kept_flying, threshold_pct=20, grace_s=3)
    (violation,) = outcome.violations
    assert violation.drone_ids == ("drone_1",) and violation.timestamp_s == 5


def test_reaches_only_counts_the_window_it_is_given():
    at_home = _sample("drone_2", Vector3(0, 3, 0))
    away = _sample("drone_2", Vector3(30, 3, 5))
    one = _sample("drone_1", Vector3(0, 0, 0))
    trace = _trace([_frame(1.0, one, at_home), _frame(20.0, one, away), _frame(40.0, one, away)])

    outcome = _check(
        "reaches", trace, drone="drone_2", position=[0, 3, 0], tolerance_m=1, from_s=10, by_s=40
    )

    assert not outcome.passed
    assert outcome.violations[0].measured_value == pytest.approx(30.4138, abs=1e-3)


def test_final_position_measures_the_last_frame():
    trace = _trace(
        [
            _frame(
                60.0, _sample("drone_1", Vector3(20, 0.5, 0)), _sample("drone_2", Vector3(0, 3, 0))
            )
        ]
    )

    outcome = _check("final_position", trace, drone="drone_1", position=[20, 0, 0], tolerance_m=1.0)

    assert outcome.passed and outcome.measured == 0.5


def test_formation_error_compares_followers_with_the_leader_plus_their_slot():
    mission = {"type": "formation", "formation": "line", "drone_count": 2, "spacing_m": 3.0}
    trace = _trace(
        [
            _frame(
                10.0, _sample("drone_1", Vector3(10, 0, 5)), _sample("drone_2", Vector3(7, 0, 5))
            ),
            _frame(
                11.0, _sample("drone_1", Vector3(11, 0, 5)), _sample("drone_2", Vector3(6, 0, 5))
            ),
        ],
        missions=[(1.0, MISSION, mission)],
    )

    outcome = _check("formation_error", trace, max_m=1.0)

    assert outcome.measured == 2.0  # at t=11 drone_2 is 2 m behind its slot at (8, 0, 5)
    assert outcome.violations[0].timestamp_s == 11.0


def test_never_mode_reports_the_first_time_the_mode_was_entered():
    trace = _trace(
        [
            _frame(
                t,
                _sample("drone_1", Vector3(0, 0, 5)),
                _sample("drone_2", Vector3(0, 3, 5), mode=mode),
            )
            for t, mode in ((1.0, "OFFBOARD"), (2.0, "AUTO.RTL"), (3.0, "AUTO.RTL"))
        ]
    )

    outcome = _check("never_mode", trace, drone="drone_2", mode="AUTO.RTL")

    assert not outcome.passed and outcome.violations[0].timestamp_s == 2.0


def test_every_assertion_in_the_schema_has_an_implementation():
    import json

    from swarm_coordination.scenarios.spec import SCHEMA_PATH

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    declared = set(schema["$defs"]["assertion"]["properties"])

    assert declared == set(assertions.ASSERTIONS)
