import pytest

from swarm_coordination.frames import local_to_world, parse_model_pose, world_to_local
from swarm_coordination.trajectory import Vector3


def test_world_is_local_plus_spawn_and_back():
    spawn = Vector3(0.0, 6.0, 0.0)
    local = Vector3(10.0, -1.0, 5.0)

    world = local_to_world(local, spawn)

    assert world == Vector3(10.0, 5.0, 5.0)
    assert world_to_local(world, spawn) == local


def test_heights_are_measured_from_the_drones_home_not_its_local_origin():
    # The SITL smoke's drone_1: standing on its pad, PX4 put it 2.49 m above its local
    # origin, and recorded home 2.66 m above it.
    spawn = Vector3(0.0, 0.0, 0.0)

    on_pad = local_to_world(Vector3(-0.05, 0.12, 2.49), spawn, home_height=2.66)
    target = world_to_local(Vector3(0.0, 0.0, 5.0), spawn, home_height=2.66)

    assert on_pad.z == pytest.approx(-0.17)
    assert target.z == pytest.approx(7.66)  # 5 m above the pad, in PX4's local frame
    assert local_to_world(target, spawn, home_height=2.66).z == pytest.approx(5.0)


def test_a_raised_pad_adds_its_own_height():
    spawn = Vector3(0.0, 0.0, 2.0)  # a pad on a 2 m platform

    assert local_to_world(Vector3(0.0, 0.0, 1.0), spawn, home_height=1.0).z == pytest.approx(2.0)


def test_two_drones_reporting_the_same_local_position_are_not_in_the_same_place():
    a = local_to_world(Vector3(0.0, 0.0, 5.0), Vector3(0.0, 0.0, 0.0))
    b = local_to_world(Vector3(0.0, 0.0, 5.0), Vector3(0.0, 3.0, 0.0))

    assert a.distance_to(b) == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("pose", "expected"),
    [
        ("0,3,0,0,0,0", Vector3(0.0, 3.0, 0.0)),
        (" 1.5, -2 ,0.2 ", Vector3(1.5, -2.0, 0.2)),
        ("4,5", Vector3(4.0, 5.0, 0.0)),
    ],
)
def test_model_pose_translation(pose, expected):
    assert parse_model_pose(pose) == expected


@pytest.mark.parametrize("pose", ["", "1,2,3,4,5,6,7", "a,b,c"])
def test_malformed_model_pose_is_rejected(pose):
    with pytest.raises(ValueError):
        parse_model_pose(pose)
