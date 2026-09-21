"""ROS 2 node: combines every drone's MAVROS telemetry into one `/swarm/state` message.

The other half of the rosbridge contract `mission_dispatcher_node.py` documents:
`SwarmApi.Infrastructure.RosBridgeSwarmBridge` subscribes to `/swarm/state` (a
JSON-encoded `std_msgs/String`) for `GET /swarm/state`, instead of opening one rosbridge
subscription per drone per topic — one aggregation point here is simpler than N*M
subscriptions managed on the .NET side, and it is where a future telemetry field
(e.g. a real battery percentage) gets added once, not once per consumer.
"""

from __future__ import annotations

import json

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import QoSPresetProfiles
from std_msgs.msg import String


class SwarmStateAggregatorNode(Node):
    def __init__(self) -> None:
        super().__init__("swarm_state_aggregator_node")

        self.declare_parameter("drone_count", 1)
        drone_count = int(self.get_parameter("drone_count").value)

        self._latest_pose: dict[str, PoseStamped] = {}
        for i in range(1, drone_count + 1):
            namespace = f"drone_{i}"
            self.create_subscription(
                PoseStamped,
                f"/{namespace}/mavros/local_position/pose",
                self._make_pose_handler(namespace),
                QoSPresetProfiles.SENSOR_DATA.value,
            )

        self._state_pub = self.create_publisher(String, "/swarm/state", 10)
        self.create_timer(0.2, self._publish_state)  # 5 Hz: comfortably under the < 1s M3 budget
        self.get_logger().info(
            f"swarm_state_aggregator_node ready for {drone_count} drone(s)"
        )

    def _make_pose_handler(self, namespace: str):
        def _handler(msg: PoseStamped) -> None:
            self._latest_pose[namespace] = msg

        return _handler

    def _publish_state(self) -> None:
        drones = []
        for namespace, pose in self._latest_pose.items():
            drones.append(
                {
                    "id": namespace,
                    "x": pose.pose.position.x,
                    "y": pose.pose.position.y,
                    "z": pose.pose.position.z,
                }
            )

        out = String()
        out.data = json.dumps({"drones": drones})
        self._state_pub.publish(out)


def main() -> None:
    rclpy.init()
    node = SwarmStateAggregatorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
