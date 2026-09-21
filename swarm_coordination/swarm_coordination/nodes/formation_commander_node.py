"""ROS 2 node: computes one follower's target pose from the leader's current position.

One instance per follower drone (see `launch/spawn_swarm.launch.py`), each parameterized
with its own offset index into the shared formation. Formation math is
`formation.follower_targets` (rclpy-free, unit tested); this node only subscribes,
computes, and publishes.
"""

from __future__ import annotations

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import QoSPresetProfiles

from ..formation import follower_targets, line_formation, v_formation
from ..trajectory import Vector3

FORMATIONS = {
    "line": line_formation,
    "v": v_formation,
}


class FormationCommanderNode(Node):
    def __init__(self) -> None:
        super().__init__("formation_commander_node")

        self.declare_parameter("formation_type", "line")
        self.declare_parameter("follower_count", 1)
        self.declare_parameter("follower_index", 0)
        self.declare_parameter("spacing_m", 2.0)
        self.declare_parameter("leader_position_topic", "/drone_1/mavros/local_position/pose")

        formation_type = str(self.get_parameter("formation_type").value)
        if formation_type not in FORMATIONS:
            raise ValueError(
                f"unknown formation_type '{formation_type}', expected one of {list(FORMATIONS)}"
            )

        follower_count = int(self.get_parameter("follower_count").value)
        self._follower_index = int(self.get_parameter("follower_index").value)
        if not (0 <= self._follower_index < follower_count):
            raise ValueError("follower_index must be in [0, follower_count)")

        spacing_m = float(self.get_parameter("spacing_m").value)
        self._offsets = FORMATIONS[formation_type](follower_count, spacing_m)

        self._setpoint_pub = self.create_publisher(
            PoseStamped, "mavros/setpoint_position/local", 10
        )
        leader_topic = str(self.get_parameter("leader_position_topic").value)
        self.create_subscription(
            PoseStamped,
            leader_topic,
            self._on_leader_position,
            QoSPresetProfiles.SENSOR_DATA.value,
        )
        self.get_logger().info(
            f"formation_commander_node ready: follower {self._follower_index}/{follower_count} "
            f"in '{formation_type}' formation, tracking {leader_topic}"
        )

    def _on_leader_position(self, msg: PoseStamped) -> None:
        leader_position = Vector3(
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z
        )
        target = follower_targets(leader_position, self._offsets)[self._follower_index]

        out = PoseStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = "map"
        out.pose.position.x = target.x
        out.pose.position.y = target.y
        out.pose.position.z = target.z
        self._setpoint_pub.publish(out)


def main() -> None:
    rclpy.init()
    node = FormationCommanderNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
