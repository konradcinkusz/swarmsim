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
            _frame(1.0, _sample("drone_1", Vector3(0, 0, 5)), _sample("drone_2", Vector3(0, 3, 5))),
            _frame(
                2.0, _sample("drone_1", Vector3(0, 0, 0)), _sample("drone_2", Vector3(0, 0.1, 5))
            ),
            _frame(
                9.0, _sample("drone_1", Vector3(0, 0, 5)), _sample("drone_2", Vector3(0, 0.1, 5))
            ),
        ]
    )

    outcome = _check("min_separation", trace, min_m=1.0, to_s=5.0)

    assert outcome.passed and outcome.measured == 3.0


def test_min_separation_fails_when_nothing_was_close_enough_to_measure():
    """Fewer than two airborne drones in the window: a pass would be a check that looked
    at nothing, like a window typed after the swarm landed, or a swarm that never flew."""
    trace = _trace(
        [
            _frame(1.0, _sample("drone_1", Vector3(0, 0, 0)), _sample("drone_2", Vector3(0, 3, 5))),
            _frame(9.0, _sample("drone_1", Vector3(0, 0, 5)), _sample("drone_2", Vector3(0, 3, 5))),
        ]
    )

    outcome = _check("min_separation", trace, min_m=1.0, to_s=5.0)

    assert not outcome.passed and outcome.measured is None
    (violation,) = outcome.violations
    assert violation.drone_ids == () and violation.timestamp_s is None
    assert "between t=0 s and t=5 s" in violation.description
    assert "no separation was measured" in violation.description


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


def _formation_trace(frames, drone_count=2, formation="line"):
    mission = {
        "type": "formation",
        "formation": formation,
        "drone_count": drone_count,
        "spacing_m": 3.0,
    }
    return _trace(frames, missions=[(1.0, MISSION, mission)])


def test_formation_error_fails_when_the_formation_was_not_flying_in_the_window():
    """follower_comms_blip once checked from 40 s, after the formation had landed (37 s)."""
    trace = _formation_trace(
        [
            _frame(
                t,
                _sample("drone_1", Vector3(t, 0, 5)),
                _sample("drone_2", Vector3(t - 3, 0, 5)),
            )
            for t in (10.0, 11.0, 12.0)
        ]
        + [
            _frame(
                t,
                _sample("drone_1", Vector3(12, 0, 0), armed=False, mode="AUTO.LAND"),
                _sample("drone_2", Vector3(9, 0, 0), armed=False, mode="AUTO.LAND"),
            )
            for t in (40.0, 41.0)
        ]
    )

    assert _check("formation_error", trace, max_m=1.0, from_s=10.0).passed

    outcome = _check("formation_error", trace, max_m=1.0, from_s=40.0)

    assert not outcome.passed and outcome.measured is None
    (violation,) = outcome.violations
    assert violation.drone_ids == () and violation.timestamp_s is None
    assert violation.description == (
        "no frame from t=40 s on had 2 drones flying the line formation under offboard "
        "control, so its error was not measured (they did from t=10 s to t=12 s)"
    )


def test_formation_error_fails_when_a_drone_of_the_formation_never_flew():
    mission = {"type": "formation", "formation": "line", "drone_count": 3, "spacing_m": 3.0}
    homes = {**HOMES, "drone_3": Vector3(0.0, 6.0, 0.0)}
    trace = Trace("hand_built", "reference", 1, 0.1, homes)
    trace.missions = [(1.0, MISSION, mission)]
    trace.frames = [
        Frame(
            t,
            (
                _sample("drone_1", Vector3(t, 0, 5)),
                _sample("drone_2", Vector3(t - 3, 0, 5)),
                _sample("drone_3", Vector3(0, 6, 0), armed=False, mode="AUTO.LOITER"),
            ),
            MISSION,
            False,
        )
        for t in (10.0, 11.0)
    ]

    outcome = _check("formation_error", trace, max_m=1.0)

    assert not outcome.passed and outcome.measured is None
    assert "that many were never flying at once in this run" in outcome.violations[0].description


def test_formation_error_does_not_guess_when_more_drones_fly_than_the_formation_needs():
    """Which of three flying drones are the formation's two is the swarm's business, and a
    frame that cannot say is not measured."""
    trace = _formation_trace(
        [
            Frame(
                1.0,
                (
                    _sample("drone_1", Vector3(10, 0, 5)),
                    _sample("drone_2", Vector3(7, 0, 5)),
                    _sample("drone_3", Vector3(0, 6, 5)),
                ),
                MISSION,
                False,
            )
        ]
    )
    trace.homes = {**HOMES, "drone_3": Vector3(0.0, 6.0, 0.0)}

    outcome = _check("formation_error", trace, max_m=1.0)

    assert not outcome.passed and outcome.measured is None


def test_formation_error_does_not_assume_who_leads_or_who_takes_which_slot():
    """The reference swarm lets drone_1 lead and gives the slots in id order. A swarm that
    elects drone_2, with drone_3 right behind it and drone_1 last, flies the same line."""
    homes = {**HOMES, "drone_3": Vector3(0.0, 6.0, 0.0)}
    trace = Trace("hand_built", "reference", 1, 0.1, homes)
    mission = {"type": "formation", "formation": "line", "drone_count": 3, "spacing_m": 3.0}
    trace.missions = [(1.0, MISSION, mission)]
    trace.frames = [
        Frame(
            t,
            (
                _sample("drone_1", Vector3(t - 6, 0, 5)),
                _sample("drone_2", Vector3(t, 0, 5)),
                _sample("drone_3", Vector3(t - 3, 0, 5)),
            ),
            MISSION,
            False,
        )
        for t in (10.0, 11.0)
    ]

    outcome = _check("formation_error", trace, max_m=0.5)

    assert outcome.passed and outcome.measured == 0.0
    assert not _check("formation_error", trace, max_m=0.5, leader="drone_1").passed  # pinned


def test_formation_error_measures_the_shape_and_reports_the_worst_frame():
    trace = _formation_trace(
        [
            _frame(
                t,
                _sample("drone_1", Vector3(10, 0, 5)),
                _sample("drone_2", Vector3(7 - slip, 0, 5)),
            )
            for t, slip in ((10.0, 0.0), (11.0, 1.5), (12.0, 0.5))
        ]
    )

    outcome = _check("formation_error", trace, max_m=1.0)

    assert not outcome.passed and outcome.measured == 1.5
    (violation,) = outcome.violations
    assert violation.drone_ids == ("drone_2", "drone_1") and violation.timestamp_s == 11.0
    assert violation.measured_value == 1.5 and violation.threshold == 1.0


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


def test_an_assertion_about_an_absence_passes_having_measured_nothing():
    """never_mode claims the mode never happened; "nothing happened" is its pass, so the
    rule that a distance check must measure something does not apply to it."""
    trace = _trace(
        [
            _frame(1.0, _sample("drone_1", Vector3(0, 0, 5)), _sample("drone_2", Vector3(0, 3, 5))),
        ]
    )

    outcome = _check("never_mode", trace, drone="drone_2", mode="AUTO.RTL")

    assert outcome.passed and outcome.measured is None


def test_every_assertion_in_the_schema_has_an_implementation():
    import json

    from swarm_coordination.scenarios.spec import schema_text

    schema = json.loads(schema_text())
    declared = set(schema["$defs"]["assertion"]["properties"])

    assert declared == set(assertions.ASSERTIONS)
