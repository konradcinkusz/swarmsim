"""ROS 2 node: the swarm's single runtime mission entry point.

Subscribes to `/swarm/mission` (a JSON-encoded `std_msgs/String` — the same message
`SwarmApi.Infrastructure.RosBridgeSwarmBridge` publishes over rosbridge on
`POST /missions`), plans per-drone waypoint assignments with the pure
`mission_planning.plan_swarm_waypoints`, and publishes each assigned drone's list to
its own `<namespace>/mission/waypoints` topic, where `waypoint_follower_node` picks it
up at runtime (see that node's `_on_mission_waypoints`).

Expected `/swarm/mission` payload:

    {"type": "waypoint"|"formation", "waypoints": [[x,y,z], ...],
     "drone_count": N, "spacing_m": S}
"""

from __future__ import annotations

import json

import rclpy
from geometry_msgs.msg import Pose, PoseArray
from rclpy.node import Node
from std_msgs.msg import String

from ..mission_planning import plan_swarm_waypoints
from ..trajectory import Vector3


class MissionDispatcherNode(Node):
    def __init__(self) -> None:
        super().__init__("mission_dispatcher_node")

        self._publishers: dict[str, rclpy.publisher.Publisher] = {}
        self.create_subscription(String, "/swarm/mission", self._on_mission, 10)
        self.get_logger().info("mission_dispatcher_node ready, listening on /swarm/mission")

    def _publisher_for(self, drone_namespace: str):
        if drone_namespace not in self._publishers:
            self._publishers[drone_namespace] = self.create_publisher(
                PoseArray, f"/{drone_namespace}/mission/waypoints", 10
            )
        return self._publishers[drone_namespace]

    def _on_mission(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
            base_waypoints = [Vector3(*wp) for wp in payload["waypoints"]]
            plan = plan_swarm_waypoints(
                mission_type=payload["type"],
                base_waypoints=base_waypoints,
                drone_count=int(payload["drone_count"]),
                spacing_m=float(payload.get("spacing_m", 2.0)),
            )
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self.get_logger().error(f"rejected malformed /swarm/mission payload: {exc}")
            return

        for drone_namespace, waypoints in plan.items():
            out = PoseArray()
            out.header.stamp = self.get_clock().now().to_msg()
            out.header.frame_id = "map"
            for wp in waypoints:
                pose = Pose()
                pose.position.x = wp.x
                pose.position.y = wp.y
                pose.position.z = wp.z
                out.poses.append(pose)
            self._publisher_for(drone_namespace).publish(out)

        self.get_logger().info(f"dispatched mission to {list(plan.keys())}")


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
