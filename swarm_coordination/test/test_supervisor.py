"""The battery and supersede policy in supervisor.MissionSupervisor, edge by edge."""

import pytest

from swarm_coordination.mission_planning import CommandMessage, MissionMessage
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
