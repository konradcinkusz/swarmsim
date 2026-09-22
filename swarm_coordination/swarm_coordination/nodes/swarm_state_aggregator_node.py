"""ROS 2 node: combines every drone's readings into one `/swarm/state` message.

The other half of the rosbridge contract `mission_dispatcher_node.py` documents:
`SwarmApi.Infrastructure.RosBridgeSwarmBridge` subscribes to `/swarm/state` (JSON in a
`std_msgs/String`, contracts/rosbridge/swarm_state.v1.schema.json) instead of opening one
rosbridge subscription per drone per topic. Positions come from each drone controller's
`world_pose` — already in the shared world frame — and armed/mode/battery straight from
MAVROS. The payload is built by the rclpy-free `swarm_state` module.
"""

from __future__ import annotations

import json

import rclpy
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import State
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String

from ..swarm_state import DroneReadings, battery_percent, build_state_message
from ..trajectory import Vector3

LATCHED = QoSProfile(
    depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE
)


class SwarmStateAggregatorNode(Node):
    def __init__(self) -> None:
        super().__init__("swarm_state_aggregator_node")
        self.declare_parameter("drones", ["drone_1"])
        self.declare_parameter("rate_hz", 5.0)  # comfortably under the < 1 s M3 budget
        drones = [str(d) for d in self.get_parameter("drones").value]

        self._readings = {drone: DroneReadings() for drone in drones}
        self._mission_id: str | None = None
        self._mission_drones: list[str] = []

        for drone in drones:
            self.create_subscription(PoseStamped, f"/{drone}/world_pose", self._on_pose(drone), 10)
            self.create_subscription(
                State, f"/{drone}/mavros/state", self._on_state(drone), qos_profile_sensor_data
            )
            self.create_subscription(
                BatteryState,
                f"/{drone}/mavros/battery",
                self._on_battery(drone),
                qos_profile_sensor_data,
            )
            self.create_subscription(
                String, f"/{drone}/mission/progress", self._on_progress(drone), 10
            )
        self.create_subscription(String, "/swarm/active_mission", self._on_active_mission, LATCHED)

        self._state_pub = self.create_publisher(String, "/swarm/state", 10)
        rate_hz = float(self.get_parameter("rate_hz").value)
        self.create_timer(1.0 / rate_hz, self._publish_state)
        self.get_logger().info(f"swarm_state_aggregator_node ready for {drones}")

    def _now_s(self) -> float:
        return self.get_clock().now().nanoseconds * 1e-9

    def _on_pose(self, drone: str):
        def handler(msg: PoseStamped) -> None:
            p = msg.pose.position
            readings = self._readings[drone]
            readings.position_world = Vector3(p.x, p.y, p.z)
            readings.position_time_s = self._now_s()

        return handler

    def _on_state(self, drone: str):
        def handler(msg: State) -> None:
            self._readings[drone].armed = bool(msg.armed)
            self._readings[drone].mode = str(msg.mode)

        return handler

    def _on_battery(self, drone: str):
        def handler(msg: BatteryState) -> None:
            self._readings[drone].battery_pct = battery_percent(msg.percentage)

        return handler

    def _on_progress(self, drone: str):
        def handler(msg: String) -> None:
            try:
                progress = json.loads(msg.data)
            except ValueError:
                return
            readings = self._readings[drone]
            readings.mission_id = progress.get("mission_id")
            readings.waypoint_index = progress.get("waypoint_index")
            readings.waypoint_count = progress.get("waypoint_count")
            readings.complete = bool(progress.get("complete"))

        return handler

    def _on_active_mission(self, msg: String) -> None:
        try:
            active = json.loads(msg.data)
        except ValueError:
            return
        self._mission_id = active.get("mission_id")
        self._mission_drones = [str(d) for d in active.get("drones", [])]

    def _publish_state(self) -> None:
        message = build_state_message(
            self._readings, self._now_s(), self._mission_id, self._mission_drones
        )
        self._state_pub.publish(String(data=json.dumps(message)))


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
