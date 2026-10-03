"""The battery and supersede policy in supervisor.MissionSupervisor, edge by edge."""

import pytest

from swarm_coordination.mission_planning import (
    CommandMessage,
    MissionMessage,
    MissionPlan,
    plan_mission,
)
from swarm_coordination.supervisor import (
    ActiveMission,
    Assign,
    Command,
    MissionSupervisor,
    Rejected,
    Slot,
    TaskDropped,
)
from swarm_coordination.trajectory import Vector3

MISSION = "3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c"
OTHER = "0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b"
ROUTE = [Vector3(0.0, 0.0, 5.0), Vector3(10.0, 0.0, 5.0), Vector3(20.0, 0.0, 5.0)]


def _mission(mission_type="waypoint", count=2, mission_id=MISSION, formation="line"):
    return MissionMessage(mission_id, mission_type, formation, list(ROUTE), count, 3.0)


def _supervisor(count=4, battery=90.0):
    drones = [f"drone_{i}" for i in range(1, count + 1)]
    supervisor = MissionSupervisor(drones, battery_threshold_pct=20.0)
    for drone in drones:
        supervisor.observe_battery(drone, battery)
    return supervisor


def _of(actions, kind):
    return [a for a in actions if isinstance(a, kind)]


def test_a_mission_is_planned_onto_the_first_drones_in_id_order():
    actions = _supervisor().start(_mission(count=2))

    assert [a.drone for a in _of(actions, Assign)] == ["drone_1", "drone_2"]
    assert actions[-1] == ActiveMission(MISSION, ("drone_1", "drone_2"))


def test_drones_known_to_be_low_are_skipped_and_unknown_batteries_block_nothing():
    supervisor = MissionSupervisor(["drone_1", "drone_2", "drone_3"], 20.0)
    supervisor.observe_battery("drone_1", 19.9)  # drone_2 and drone_3 never reported

    actions = supervisor.start(_mission(count=2))

    assert [a.drone for a in _of(actions, Assign)] == ["drone_2", "drone_3"]


def test_a_mission_needing_more_fit_drones_than_exist_is_rejected_with_the_reason():
    supervisor = _supervisor(count=2)
    supervisor.observe_battery("drone_2", 5.0)

    actions = supervisor.start(_mission(count=2))

    assert len(actions) == 1 and isinstance(actions[0], Rejected)
    assert "drone_2 below 20% battery" in actions[0].reason
    assert supervisor.active_mission_id is None


def test_a_low_drone_hands_the_rest_of_its_route_to_the_first_idle_drone_and_goes_home():
    supervisor = _supervisor(count=4)
    supervisor.start(_mission(count=2))
    supervisor.observe_progress("drone_1", MISSION, waypoint_index=1, complete=False)

    supervisor.observe_battery("drone_1", 15.0)
    actions = supervisor.reallocate()

    assert Command("drone_1", "rtl") in actions
    assert Assign("drone_3", MISSION, tuple(ROUTE[1:])) in actions
    assert actions[-1] == ActiveMission(MISSION, ("drone_2", "drone_3"))
    assert supervisor.reallocate() == []  # decided once, not every tick


def test_a_replacement_for_a_leader_becomes_the_leader_its_followers_track():
    supervisor = _supervisor(count=4)
    supervisor.start(_mission("formation", count=3))

    supervisor.observe_battery("drone_1", 10.0)
    actions = supervisor.reallocate()

    assert Assign("drone_4", MISSION, tuple(ROUTE)) in actions
    assert {a.drone for a in _of(actions, Slot) if a.leader == "drone_4"} == {
        "drone_2",
        "drone_3",
    }


def test_a_low_follower_is_replaced_in_the_same_slot():
    supervisor = _supervisor(count=4)
    start = supervisor.start(_mission("formation", count=3))
    slot = next(a for a in _of(start, Slot) if a.drone == "drone_3")

    supervisor.observe_battery("drone_3", 10.0)
    actions = supervisor.reallocate()

    assert Slot("drone_4", MISSION, "drone_1", slot.offset) in actions
    assert Command("drone_3", "rtl") in actions


def test_with_nobody_to_take_over_the_drone_still_goes_home_and_the_task_is_dropped():
    supervisor = _supervisor(count=2)
    supervisor.start(_mission(count=2))

    supervisor.observe_battery("drone_2", 12.0)
    actions = supervisor.reallocate()

    assert Command("drone_2", "rtl") in actions
    (dropped,) = _of(actions, TaskDropped)
    assert dropped.drone == "drone_2" and "12.0%" in dropped.reason
    # Still part of the mission, so the mission cannot report complete without its lane.
    assert supervisor.mission_drones() == ["drone_1", "drone_2"]
    assert supervisor.reallocate() == []


def test_an_idle_drone_that_is_itself_low_or_unknown_is_never_the_replacement():
    supervisor = MissionSupervisor(["drone_1", "drone_2", "drone_3"], 20.0)
    supervisor.observe_battery("drone_1", 80.0)
    supervisor.observe_battery("drone_2", 18.0)  # drone_3: never reported
    supervisor.start(_mission(count=1))

    supervisor.observe_battery("drone_1", 10.0)
    actions = supervisor.reallocate()

    assert _of(actions, Assign) == [] and len(_of(actions, TaskDropped)) == 1


def test_a_drone_that_finished_its_task_is_left_alone_when_its_battery_drops():
    supervisor = _supervisor(count=3)
    supervisor.start(_mission(count=2))
    supervisor.observe_progress("drone_1", MISSION, waypoint_index=3, complete=True)

    supervisor.observe_battery("drone_1", 5.0)

    assert supervisor.reallocate() == []


def test_progress_for_another_mission_is_ignored():
    supervisor = _supervisor(count=3)
    supervisor.start(_mission(count=2))
    supervisor.observe_progress("drone_1", OTHER, waypoint_index=3, complete=True)

    supervisor.observe_battery("drone_1", 5.0)

    assert Command("drone_1", "rtl") in supervisor.reallocate()


def test_a_new_mission_sends_home_the_drones_it_no_longer_uses():
    supervisor = _supervisor(count=3)
    supervisor.start(_mission(count=3))

    actions = supervisor.start(_mission(count=1, mission_id=OTHER))

    assert _of(actions, Command) == [Command("drone_2", "rtl"), Command("drone_3", "rtl")]
    assert [a.drone for a in _of(actions, Assign)] == ["drone_1"]


def test_a_command_reaches_every_drone_and_ends_the_mission():
    supervisor = _supervisor(count=2)
    supervisor.start(_mission(count=1))

    actions = supervisor.command(CommandMessage("land", MISSION))

    assert _of(actions, Command) == [Command("drone_1", "land"), Command("drone_2", "land")]
    assert actions[-1] == ActiveMission(None, ())
    assert supervisor.reallocate() == []


@pytest.mark.parametrize("battery", [None, 20.0, 55.0])
def test_nothing_is_reallocated_at_or_above_the_threshold_or_when_unknown(battery):
    supervisor = _supervisor(count=3)
    supervisor.start(_mission(count=2))

    supervisor.observe_battery("drone_1", battery)

    assert supervisor.reallocate() == []


# --- a planner decides who flies and who leads ------------------------------------------


def _report(supervisor, **where):
    for drone, (x, y) in where.items():
        supervisor.observe_position(drone, Vector3(x, y, 0.0), armed=False)


def _nearest_first(mission, drones, positions):
    """A planner: the drones nearest the start of the route fly it, the nearest one leading."""
    ranked = sorted(drones, key=lambda d: positions[d].distance_to(mission.waypoints[0]))
    return plan_mission(mission, ranked[: mission.drone_count])


def _pads(supervisor):
    _report(supervisor, drone_1=(0, 0), drone_2=(0, 3), drone_3=(0, 6), drone_4=(0, 9))


def test_a_planner_chooses_who_flies_and_who_leads_from_where_the_drones_are():
    supervisor = MissionSupervisor(
        [f"drone_{i}" for i in range(1, 5)], 20.0, planner=_nearest_first
    )
    _pads(supervisor)
    mission = MissionMessage(
        MISSION, "formation", "line", [Vector3(0.0, 8.0, 5.0), Vector3(20.0, 8.0, 5.0)], 3, 3.0
    )

    actions = supervisor.start(mission)

    assert [a.drone for a in _of(actions, Assign)] == ["drone_4"]  # the nearest leads
    assert [(a.drone, a.leader) for a in _of(actions, Slot)] == [
        ("drone_3", "drone_4"),
        ("drone_2", "drone_4"),
    ]
    assert actions[-1] == ActiveMission(MISSION, ("drone_2", "drone_3", "drone_4"))


def test_the_planner_is_offered_the_drones_fit_to_fly_and_the_positions_reported_so_far():
    seen = {}

    def planner(mission, drones, positions):
        seen.update(drones=list(drones), positions=dict(positions))
        return plan_mission(mission, drones[: mission.drone_count])

    supervisor = _supervisor(count=4)
    supervisor._planner = planner
    supervisor.observe_battery("drone_2", 5.0)  # low: not offered, its position not passed on
    _report(supervisor, drone_1=(1, 0), drone_2=(2, 0), drone_3=(3, 0))  # drone_4 never reports
    supervisor.observe_position("drone_3", Vector3(4.0, 0.0, 0.0), armed=True)  # the latest wins
    supervisor.observe_position("drone_1", None, armed=True)  # no fix: nothing recorded
    supervisor.observe_position("drone_9", Vector3(9.0, 0.0, 0.0), armed=False)  # not in the fleet

    supervisor.start(_mission(count=2))

    assert seen["drones"] == ["drone_1", "drone_3", "drone_4"]
    assert seen["positions"] == {
        "drone_1": Vector3(1.0, 0.0, 0.0),
        "drone_3": Vector3(4.0, 0.0, 0.0),
    }


def test_a_hand_over_after_a_planned_mission_works_on_the_plan_the_planner_made():
    supervisor = MissionSupervisor(
        [f"drone_{i}" for i in range(1, 5)], 20.0, planner=_nearest_first
    )
    for drone in supervisor.drones:
        supervisor.observe_battery(drone, 90.0)
    _pads(supervisor)
    mission = MissionMessage(
        MISSION, "formation", "line", [Vector3(0.0, 8.0, 5.0), Vector3(20.0, 8.0, 5.0)], 3, 3.0
    )
    supervisor.start(mission)  # drone_4 leads drone_3 and drone_2; drone_1 is idle

    supervisor.observe_battery("drone_4", 10.0)
    actions = supervisor.reallocate()

    assert [(a.drone, a.leader) for a in _of(actions, Slot)] == [
        ("drone_3", "drone_1"),
        ("drone_2", "drone_1"),
    ]
    assert [a.drone for a in _of(actions, Assign)] == ["drone_1"]  # the idle drone leads on


def _good_then(bad):
    """A planner that plans the first mission and answers the second with ``bad``."""
    calls = []

    def planner(mission, drones, positions):
        calls.append(mission.mission_id)
        if len(calls) == 1:
            return plan_mission(mission, drones[: mission.drone_count])
        return bad(mission, drones, positions)

    return planner


def _plan(**parts):
    """A plan for the second mission, OTHER, which the planner answers badly."""
    return MissionPlan(OTHER, **parts)


OFFSET = Vector3(-3.0, 0.0, 0.0)


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (lambda m, d, p: None, "it returned NoneType, not a MissionPlan"),
        (lambda m, d, p: plan_mission(_mission(mission_id=MISSION), d[:2]), "it is for mission"),
        (lambda m, d, p: plan_mission(_mission(count=1, mission_id=OTHER), d[:1]), "uses 1 drone"),
        (lambda m, d, p: plan_mission(m, ["drone_1", "drone_9"]), "drone_9: not among"),
        (
            lambda m, d, p: _plan(
                paths={"drone_1": ROUTE}, followers={"drone_2": ("drone_3", OFFSET)}
            ),
            "drone_2 follows drone_3, which flies no path",
        ),
        (
            lambda m, d, p: _plan(
                paths={"drone_1": ROUTE, "drone_2": ROUTE},
                followers={"drone_2": ("drone_1", OFFSET)},
            ),
            "drone_2 would fly a path and follow a leader at once",
        ),
        (
            lambda m, d, p: _plan(paths={"drone_1": [], "drone_2": ROUTE}),
            "drone_1 would fly an empty path",
        ),
    ],
)
def test_a_plan_that_cannot_be_flown_is_rejected_with_the_reason_and_nothing_changes(bad, reason):
    supervisor = _supervisor(count=4)
    supervisor._planner = _good_then(bad)
    supervisor.start(_mission(count=2))

    actions = supervisor.start(_mission(count=2, mission_id=OTHER))

    (rejected,) = actions
    assert isinstance(rejected, Rejected) and rejected.mission_id == OTHER
    assert rejected.reason.startswith("the planner's plan cannot be flown: ")
    assert reason in rejected.reason
    assert supervisor.active_mission_id == MISSION  # the mission in flight flies on


def test_a_planner_that_raises_rejects_the_mission_and_the_one_in_flight_flies_on():
    def broken(mission, drones, positions):
        raise RuntimeError("no route")

    supervisor = _supervisor(count=4)
    supervisor._planner = _good_then(broken)
    supervisor.start(_mission(count=2))

    actions = supervisor.start(_mission(count=2, mission_id=OTHER))

    assert actions == [Rejected(OTHER, "the planner failed: RuntimeError: no route")]
    assert supervisor.active_mission_id == MISSION
