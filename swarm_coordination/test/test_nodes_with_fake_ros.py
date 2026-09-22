"""The node adapters, driven through fake_ros: topic names, frames, and what each node
publishes in answer to what it hears. Real DDS and PX4 are the SITL smoke's job."""

import ast
import json
import types
from pathlib import Path

import fake_ros
import pytest

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "rosbridge"
MISSION = "3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c"


@pytest.fixture
def bus():
    bus = fake_ros.install()
    yield bus
    import sys

    for name in [
        n
        for n in sys.modules
        if n in ("rclpy", "rclpy.node", "rclpy.qos") or n.endswith("_msgs.msg")
    ]:
        del sys.modules[name]


def _node(bus, module, cls, namespace="/", **parameters):
    bus.namespace = namespace
    bus.parameter_overrides = parameters
    mod = __import__(f"swarm_coordination.nodes.{module}", fromlist=[cls])
    return getattr(mod, cls)()


def _json(msg):
    return json.loads(msg.data)


def test_a_node_that_takes_over_rclpy_s_own_attributes_fails_here_as_in_rclpy(bus):
    # rclpy.node.Node keeps its publishers, timers, clock and logger in attributes of the
    # node itself. A subclass that assigns one of them breaks rclpy later, somewhere else:
    # the dispatcher did, and died at start in every SITL smoke run while these tests passed.
    from rclpy.node import Node

    class TakesOver(Node):
        def __init__(self):
            super().__init__("takes_over")
            self._publishers = {}

    with pytest.raises(AttributeError, match="_publishers"):
        TakesOver()


def test_no_node_assigns_an_attribute_rclpy_keeps_its_own_state_in():
    # The fake refuses such an assignment only on the paths a test drives; this reads
    # every assignment in every node.
    nodes = Path(__file__).resolve().parents[1] / "swarm_coordination" / "nodes"
    taken = []
    for source in sorted(nodes.glob("*.py")):
        for statement in ast.walk(ast.parse(source.read_text())):
            if isinstance(statement, ast.Assign):
                targets = statement.targets
            elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
                targets = [statement.target]
            else:
                continue
            taken += [
                f"{source.name}:{statement.lineno} self.{target.attr}"
                for target in targets
                if isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr in fake_ros.RCLPY_NODE_ATTRIBUTES
            ]
    assert taken == []


def test_the_dispatcher_can_reach_every_drone_before_the_first_mission(bus):
    # A ROS 2 publisher created just before its first message may not be matched with its
    # subscribers yet, and a volatile message sent then is lost: every drone's topics exist
    # from the start.
    _node(bus, "mission_dispatcher_node", "MissionDispatcherNode", drones=["drone_1", "drone_2"])

    for drone in ("drone_1", "drone_2"):
        for topic in ("mission/assignment", "mission/slot", "mission/command"):
            assert f"/{drone}/{topic}" in bus.publishers


def test_the_dispatcher_turns_the_contract_example_into_a_path_and_two_slots(bus):
    _node(
        bus,
        "mission_dispatcher_node",
        "MissionDispatcherNode",
        drones=["drone_1", "drone_2", "drone_3"],
    )

    bus.publish(
        "/swarm/mission",
        fake_ros.String((CONTRACTS / "examples" / "swarm_mission.json").read_text()),
    )

    (assignment,) = bus.messages("/drone_1/mission/assignment")
    assert _json(assignment) == {
        "mission_id": MISSION,
        "waypoints": [[0.0, 0.0, 5.0], [10.0, 0.0, 5.0]],
    }
    assert _json(bus.messages("/drone_2/mission/slot")[0])["offset"] == [-2.5, 2.5, 0.0]
    assert _json(bus.messages("/drone_3/mission/slot")[0])["leader"] == "drone_1"
    assert _json(bus.messages("/swarm/active_mission")[-1]) == {
        "mission_id": MISSION,
        "drones": ["drone_1", "drone_2", "drone_3"],
    }


def test_the_dispatcher_refuses_a_mission_needing_drones_that_are_not_running(bus):
    node = _node(bus, "mission_dispatcher_node", "MissionDispatcherNode", drones=["drone_1"])

    bus.publish(
        "/swarm/mission",
        fake_ros.String((CONTRACTS / "examples" / "swarm_mission.json").read_text()),
    )

    assert bus.messages("/drone_1/mission/assignment") == []
    assert any(level == "error" and "drone_2" in text for level, text in node.get_logger().lines)


def test_the_dispatcher_ignores_a_malformed_mission(bus):
    _node(bus, "mission_dispatcher_node", "MissionDispatcherNode", drones=["drone_1"])

    bus.publish("/swarm/mission", fake_ros.String("{nope"))

    assert bus.messages("/drone_1/mission/assignment") == []


def test_a_command_reaches_every_drone_and_clears_the_active_mission(bus):
    _node(bus, "mission_dispatcher_node", "MissionDispatcherNode", drones=["drone_1", "drone_2"])

    bus.publish(
        "/swarm/command",
        fake_ros.String((CONTRACTS / "examples" / "swarm_command.json").read_text()),
    )

    assert bus.messages("/drone_1/mission/command")[0].data == "rtl"
    assert bus.messages("/drone_2/mission/command")[0].data == "rtl"
    assert _json(bus.messages("/swarm/active_mission")[-1]) == {"mission_id": None, "drones": []}


def _controller(bus, namespace="/drone_2", spawn=(0.0, 3.0, 0.0)):
    return _node(
        bus,
        "drone_controller_node",
        "DroneControllerNode",
        namespace=namespace,
        spawn_x=spawn[0],
        spawn_y=spawn[1],
        spawn_z=spawn[2],
    )


def test_the_controller_publishes_its_world_pose_by_adding_the_spawn_offset(bus):
    _controller(bus)

    bus.publish("/drone_2/mavros/local_position/pose", fake_ros.pose(1.0, 0.0, 2.0))

    world = bus.messages("/drone_2/world_pose")[-1].pose.position
    assert (world.x, world.y, world.z) == (1.0, 3.0, 2.0)


def test_heights_are_measured_from_home_once_px4_reports_it(bus):
    node = _controller(bus)

    # On its pad, but 2.49 m above the local origin PX4 chose (the SITL smoke's drone_1).
    bus.publish("/drone_2/mavros/home_position/home", fake_ros.HomePosition(z=2.66))
    bus.publish("/drone_2/mavros/local_position/pose", fake_ros.pose(0.0, 0.0, 2.49))
    bus.publish(
        "/drone_2/mission/assignment",
        fake_ros.String(json.dumps({"mission_id": MISSION, "waypoints": [[0.0, 3.0, 5.0]]})),
    )
    bus.advance(0.1)
    fake_ros.fire(node, period=0.1)

    world = bus.messages("/drone_2/world_pose")[-1].pose.position
    setpoint = bus.messages("/drone_2/mavros/setpoint_position/local")[0].pose.position
    assert world.z == pytest.approx(-0.17)  # on the ground, not 2.49 m up
    assert setpoint.z == pytest.approx(2.66 - 0.17 + 2.0)  # 2 m carrot above where it is


def test_the_controller_flies_a_world_frame_path_with_local_frame_setpoints(bus):
    node = _controller(bus)
    bus.publish("/drone_2/mavros/local_position/pose", fake_ros.pose(0.0, 0.0, 0.0))
    bus.publish(
        "/drone_2/mission/assignment",
        fake_ros.String(json.dumps({"mission_id": MISSION, "waypoints": [[0.0, 3.0, 5.0]]})),
    )

    for _ in range(21):
        bus.advance(0.1)
        fake_ros.fire(node, period=0.1)

    setpoint = bus.messages("/drone_2/mavros/setpoint_position/local")[0].pose.position
    assert (setpoint.x, setpoint.y, setpoint.z) == (0.0, 0.0, 2.0)  # 2 m carrot straight up
    mode_requests = fake_ros.client(node, "/drone_2/mavros/set_mode").requests
    assert [r.custom_mode for r in mode_requests] == ["OFFBOARD"]

    bus.publish("/drone_2/mavros/state", fake_ros.State(armed=False, mode="OFFBOARD"))
    bus.advance(0.1)
    fake_ros.fire(node, period=0.1)
    assert fake_ros.client(node, "/drone_2/mavros/cmd/arming").requests[-1].value is True


def test_a_drone_that_cannot_take_off_says_why(bus):
    node = _controller(bus)
    arming = fake_ros.client(node, "/drone_2/mavros/cmd/arming")
    arming.response = types.SimpleNamespace(success=False, result=4)  # MAV_RESULT_FAILED
    fake_ros.client(node, "/drone_2/mavros/set_mode").ready = False
    bus.publish("/drone_2/mavros/local_position/pose", fake_ros.pose(0.0, 0.0, 0.0))
    bus.publish(
        "/drone_2/mission/assignment",
        fake_ros.String(json.dumps({"mission_id": MISSION, "waypoints": [[0.0, 3.0, 5.0]]})),
    )

    for _ in range(25):
        bus.advance(0.1)
        fake_ros.fire(node, period=0.1)
    warnings = [text for level, text in node.get_logger().lines if level == "warning"]
    assert warnings == ["cannot ask PX4 for OFFBOARD: mavros/set_mode is not available"]
    assert fake_ros.client(node, "/drone_2/mavros/set_mode").requests == []

    fake_ros.client(node, "/drone_2/mavros/set_mode").ready = True
    bus.publish("/drone_2/mavros/state", fake_ros.State(armed=False, mode="OFFBOARD"))
    bus.advance(0.1)
    fake_ros.fire(node, period=0.1)
    warnings = [text for level, text in node.get_logger().lines if level == "warning"]
    assert warnings[-1].startswith("PX4 refused arming:")
    assert ("info", "asking PX4 for arming") in node.get_logger().lines


def test_a_follower_subscribes_to_its_leader_and_lands_when_the_leader_finishes(bus):
    node = _controller(bus)
    bus.publish("/drone_2/mavros/local_position/pose", fake_ros.pose(0.0, 0.0, 0.0))
    bus.publish(
        "/drone_2/mission/slot",
        fake_ros.String(
            json.dumps({"mission_id": MISSION, "leader": "drone_1", "offset": [-2.0, 0.0, 0.0]})
        ),
    )
    bus.publish("/drone_1/world_pose", fake_ros.pose(10.0, 0.0, 5.0))

    bus.advance(0.1)
    fake_ros.fire(node, period=0.1)
    setpoint = bus.messages("/drone_2/mavros/setpoint_position/local")[-1].pose.position
    assert (setpoint.x, setpoint.y, setpoint.z) == (
        8.0,
        -3.0,
        5.0,
    )  # (10-2, 0, 5) minus spawn (0,3,0)

    bus.publish(
        "/drone_1/mission/progress",
        fake_ros.String(json.dumps({"mission_id": MISSION, "complete": True})),
    )
    bus.advance(0.1)
    fake_ros.fire(node, period=0.1)
    assert fake_ros.client(node, "/drone_2/mavros/set_mode").requests[-1].custom_mode == "AUTO.LAND"


def test_a_swarm_command_hands_the_controller_over_to_px4(bus):
    node = _controller(bus)
    bus.publish("/drone_2/mission/command", fake_ros.String("land"))

    bus.advance(0.1)
    fake_ros.fire(node, period=0.1)

    assert fake_ros.client(node, "/drone_2/mavros/set_mode").requests[-1].custom_mode == "AUTO.LAND"


def test_the_aggregator_publishes_contract_state_and_reports_completion(bus):
    jsonschema = pytest.importorskip("jsonschema")
    node = _node(
        bus,
        "swarm_state_aggregator_node",
        "SwarmStateAggregatorNode",
        drones=["drone_1", "drone_2"],
    )
    bus.publish(
        "/swarm/active_mission",
        fake_ros.String(json.dumps({"mission_id": MISSION, "drones": ["drone_1"]})),
    )
    bus.publish("/drone_1/world_pose", fake_ros.pose(10.0, 0.0, 0.0))
    bus.publish("/drone_1/mavros/state", fake_ros.State(armed=False, mode="AUTO.LAND"))
    bus.publish("/drone_1/mavros/battery", fake_ros.BatteryState(percentage=0.62))
    bus.publish(
        "/drone_1/mission/progress",
        fake_ros.String(
            json.dumps(
                {"mission_id": MISSION, "waypoint_index": 2, "waypoint_count": 2, "complete": True}
            )
        ),
    )

    bus.advance(0.2)
    fake_ros.fire(node)

    state = _json(bus.messages("/swarm/state")[-1])
    schema = json.loads((CONTRACTS / "swarm_state.v1.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(state)
    assert state["mission"] == {"id": MISSION, "complete": True}
    (drone,) = state["drones"]  # drone_2 was never heard from
    assert (drone["battery_pct"], drone["armed"], drone["waypoint_index"]) == (62.0, False, 2)
