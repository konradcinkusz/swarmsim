"""ROS 2 node: the swarm's single runtime entry point for missions and commands.

Subscribes to `/swarm/mission` and `/swarm/command` — JSON in a `std_msgs/String`, the
payloads in contracts/rosbridge/ that `SwarmApi.Infrastructure.RosBridgeSwarmBridge`
publishes over rosbridge. A mission is parsed and planned by the rclpy-free
`mission_planning` module; each drone then gets its part on `/<drone>/mission/assignment`
(a path) or `/<drone>/mission/slot` (a place behind the leader). A command goes to every
drone on `/<drone>/mission/command`, whatever it is doing. The current mission and its
drones are latched on `/swarm/active_mission` for the state aggregator.
"""

from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from ..mission_planning import parse_command_payload, parse_mission_payload, plan_mission

LATCHED = QoSProfile(
    depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE
)


class MissionDispatcherNode(Node):
    def __init__(self) -> None:
        super().__init__("mission_dispatcher_node")
        self.declare_parameter("drones", ["drone_1"])
        self._drones = [str(d) for d in self.get_parameter("drones").value]

        self._publishers: dict[str, object] = {}
        self._active_pub = self.create_publisher(String, "/swarm/active_mission", LATCHED)
        self.create_subscription(String, "/swarm/mission", self._on_mission, 10)
        self.create_subscription(String, "/swarm/command", self._on_command, 10)
        self._publish_active(None, [])
        self.get_logger().info(f"mission_dispatcher_node ready for {self._drones}")

    def _publisher(self, topic: str):
        if topic not in self._publishers:
            self._publishers[topic] = self.create_publisher(String, topic, 10)
        return self._publishers[topic]

    def _publish_active(self, mission_id: str | None, drones: list[str]) -> None:
        payload = {"mission_id": mission_id, "drones": drones}
        self._active_pub.publish(String(data=json.dumps(payload)))

    def _on_mission(self, msg: String) -> None:
        try:
            plan = plan_mission(parse_mission_payload(msg.data))
        except ValueError as exc:
            self.get_logger().error(f"rejected /swarm/mission: {exc}")
            return

        missing = [d for d in plan.drones if d not in self._drones]
        if missing:
            self.get_logger().error(
                f"rejected mission {plan.mission_id}: it needs {missing}, "
                f"but only {self._drones} are running"
            )
            return

        for drone, path in plan.paths.items():
            payload = {"mission_id": plan.mission_id, "waypoints": [[w.x, w.y, w.z] for w in path]}
            self._publisher(f"/{drone}/mission/assignment").publish(String(data=json.dumps(payload)))
        for drone, (leader, offset) in plan.followers.items():
            payload = {
                "mission_id": plan.mission_id,
                "leader": leader,
                "offset": [offset.x, offset.y, offset.z],
            }
            self._publisher(f"/{drone}/mission/slot").publish(String(data=json.dumps(payload)))

        self._publish_active(plan.mission_id, plan.drones)
        self.get_logger().info(f"dispatched mission {plan.mission_id} to {plan.drones}")

    def _on_command(self, msg: String) -> None:
        try:
            command = parse_command_payload(msg.data)
        except ValueError as exc:
            self.get_logger().error(f"rejected /swarm/command: {exc}")
            return

        for drone in self._drones:
            self._publisher(f"/{drone}/mission/command").publish(String(data=command.command))
        self._publish_active(None, [])
        self.get_logger().warning(f"swarm command '{command.command}' sent to {self._drones}")


def main() -> None:
    rclpy.init()
    node = MissionDispatcherNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
