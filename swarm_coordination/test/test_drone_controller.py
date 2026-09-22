"""DroneController against a toy autopilot: position follows the setpoint, OFFBOARD and
arming are granted when asked, and a mode switch sticks. Enough PX4 to check the
controller's decisions — not a flight model (that is the SITL smoke's job)."""

import pytest

from swarm_coordination.drone_controller import DroneController
from swarm_coordination.trajectory import Vector3, step_towards

MISSION = "3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c"


class ToyAutopilot:
    def __init__(self, position=None, speed_m_per_tick=1.0):
        self.position = position if position is not None else Vector3(0.0, 0.0, 0.0)
        self.armed = False
        self.mode = "POSCTL"
        self.speed = speed_m_per_tick
        self.mode_requests = []

    def apply(self, out):
        if out.request_mode is not None:
            self.mode_requests.append(out.request_mode)
            self.mode = out.request_mode
        if out.request_arm:
            self.armed = True
        if out.setpoint is not None and self.mode == "OFFBOARD" and self.armed:
            self.position = step_towards(self.position, out.setpoint, self.speed)
        if self.mode == "AUTO.LAND" and self.armed:
            ground = Vector3(self.position.x, self.position.y, 0.0)
            self.position = step_towards(self.position, ground, self.speed)
            if self.position.z == 0.0:
                self.armed = False


def fly(controller, pilot, ticks, leader=None, start_s=0.0):
    outputs = []
    for i in range(ticks):
        now = start_s + i * 0.1
        leader_position = leader(i) if callable(leader) else leader
        out = controller.tick(now, pilot.position, pilot.armed, pilot.mode, leader_position)
        pilot.apply(out)
        outputs.append(out)
    return outputs


def test_an_idle_drone_does_nothing():
    controller = DroneController("drone_1")
    pilot = ToyAutopilot()

    outputs = fly(controller, pilot, 30)

    assert all(o.setpoint is None and o.request_mode is None and not o.request_arm for o in outputs)


def test_a_path_is_flown_then_the_drone_lands_and_reports_completion():
    controller = DroneController("drone_1", warmup_ticks=5)
    pilot = ToyAutopilot()
    controller.assign_path(MISSION, [Vector3(0.0, 0.0, 5.0), Vector3(10.0, 0.0, 5.0)])

    fly(controller, pilot, 200)

    assert pilot.mode_requests[0] == "OFFBOARD"
    assert pilot.mode_requests[-1] == "AUTO.LAND"
    assert pilot.armed is False
    assert pilot.position.distance_to(Vector3(10.0, 0.0, 0.0)) < 0.6
    progress = controller.progress
    assert progress.complete is True
    assert (progress.mission_id, progress.waypoint_index, progress.waypoint_count) == (
        MISSION,
        2,
        2,
    )


def test_setpoints_are_a_carrot_no_further_than_max_step_ahead():
    controller = DroneController("drone_1", warmup_ticks=1, max_step_m=2.0)
    pilot = ToyAutopilot()
    controller.assign_path(MISSION, [Vector3(0.0, 0.0, 50.0)])

    outputs = fly(controller, pilot, 10)

    for out in outputs:
        if out.setpoint is not None:
            assert out.setpoint.z <= 50.0
    first = next(o.setpoint for o in outputs if o.setpoint is not None)
    assert first == Vector3(0.0, 0.0, 2.0)


def test_a_follower_holds_its_slot_relative_to_the_leader_and_lands_with_it():
    controller = DroneController("drone_2", warmup_ticks=3)
    pilot = ToyAutopilot(position=Vector3(0.0, 3.0, 0.0), speed_m_per_tick=3.0)
    controller.assign_slot(MISSION, "drone_1", Vector3(-2.0, 2.0, 0.0))

    def leader(i):
        return Vector3(0.1 * i, 0.0, 5.0)

    outputs = fly(controller, pilot, 60, leader=leader)
    last = [o.setpoint for o in outputs if o.setpoint is not None][-1]
    assert last == leader(59) + Vector3(-2.0, 2.0, 0.0)

    controller.leader_finished(MISSION)
    fly(controller, pilot, 40, leader=leader(59), start_s=6.0)

    assert pilot.mode_requests[-1] == "AUTO.LAND"
    assert controller.progress.complete is True


def test_a_follower_without_a_leader_position_streams_nothing():
    controller = DroneController("drone_2", warmup_ticks=1)
    pilot = ToyAutopilot()
    controller.assign_slot(MISSION, "drone_1", Vector3(-2.0, 0.0, 0.0))

    outputs = fly(controller, pilot, 20, leader=None)

    assert all(o.setpoint is None for o in outputs)


def test_leader_finishing_a_different_mission_is_ignored():
    controller = DroneController("drone_2", warmup_ticks=1)
    controller.assign_slot(MISSION, "drone_1", Vector3(-2.0, 0.0, 0.0))

    controller.leader_finished("some-other-mission")

    assert controller.progress.complete is False


@pytest.mark.parametrize(
    ("command", "mode"), [("rtl", "AUTO.RTL"), ("land", "AUTO.LAND"), ("hold", "AUTO.LOITER")]
)
def test_a_swarm_command_hands_the_drone_to_px4_and_stops_the_setpoints(command, mode):
    controller = DroneController("drone_1", warmup_ticks=1)
    pilot = ToyAutopilot()
    controller.assign_path(MISSION, [Vector3(0.0, 0.0, 5.0), Vector3(100.0, 0.0, 5.0)])
    fly(controller, pilot, 30)

    controller.command(command)
    outputs = fly(controller, pilot, 30, start_s=3.0)

    assert outputs[0].request_mode == mode
    assert all(o.setpoint is None for o in outputs)
    assert controller.progress.complete is False


def test_the_handover_is_retried_until_px4_reports_the_mode():
    controller = DroneController("drone_1", warmup_ticks=1, retry_interval_s=1.0)
    controller.command("rtl")

    # PX4 keeps reporting OFFBOARD: the request is repeated once a second, not every tick.
    requests = [
        controller.tick(0.1 * i, Vector3(0, 0, 5), True, "OFFBOARD").request_mode for i in range(25)
    ]
    later = controller.tick(3.0, Vector3(0, 0, 5), True, "AUTO.RTL").request_mode

    assert requests.count("AUTO.RTL") == 3
    assert later is None


def test_a_new_assignment_takes_over_from_a_command():
    controller = DroneController("drone_1", warmup_ticks=1)
    pilot = ToyAutopilot()
    controller.command("hold")
    controller.assign_path(MISSION, [Vector3(0.0, 0.0, 5.0)])

    outputs = fly(controller, pilot, 5)

    assert any(o.setpoint is not None for o in outputs)


def test_an_empty_path_is_rejected():
    with pytest.raises(ValueError):
        DroneController("drone_1").assign_path(MISSION, [])
