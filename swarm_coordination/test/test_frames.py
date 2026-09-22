import pytest

from swarm_coordination.frames import local_to_world, parse_model_pose, world_to_local
from swarm_coordination.trajectory import Vector3


def test_world_is_local_plus_spawn_and_back():
    spawn = Vector3(0.0, 6.0, 0.0)
    local = Vector3(10.0, -1.0, 5.0)

    world = local_to_world(local, spawn)

    assert world == Vector3(10.0, 5.0, 5.0)
    assert world_to_local(world, spawn) == local


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
