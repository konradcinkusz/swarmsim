"""ROS 2 node: drives one drone through a waypoint queue via MAVROS.

Thin I/O adapter only — arming/offboard-mode calls and topic wiring live here; the
waypoint-advance and step math is `waypoints.WaypointQueue` (rclpy-free, unit tested).
Talks to PX4 through `mavros` (`ros-humble-mavros`, a companion-computer bridge over
MAVLink), one instance per namespaced drone, per `launch/spawn_swarm.launch.py`.

The queue is seeded from `waypoints_x/y/z` launch parameters (M1/M2 manual testing),
and replaced wholesale whenever a `mission/waypoints` message arrives (M3: this is
what `mission_dispatcher_node` publishes when the API dispatches a mission) — the
control loop in `_on_control_tick` does not know or care which source is active.
"""

from __future__ import annotations

import rclpy
from geometry_msgs.msg import PoseArray, PoseStamped
from mavros_msgs.srv import CommandBool, SetMode
from rclpy.node import Node
from rclpy.qos import QoSPresetProfiles

from ..trajectory import Vector3
from ..waypoints import WaypointQueue

DEFAULT_MAX_STEP_M = 0.5
DEFAULT_TOLERANCE_M = 0.5
CONTROL_PERIOD_S = 0.1


class WaypointFollowerNode(Node):
    def __init__(self) -> None:
        super().__init__("waypoint_follower_node")

        self.declare_parameter("waypoints_x", [0.0])
        self.declare_parameter("waypoints_y", [0.0])
        self.declare_parameter("waypoints_z", [5.0])
        self.declare_parameter("tolerance_m", DEFAULT_TOLERANCE_M)
        self.declare_parameter("max_step_m", DEFAULT_MAX_STEP_M)

        xs = self.get_parameter("waypoints_x").value
        ys = self.get_parameter("waypoints_y").value
        zs = self.get_parameter("waypoints_z").value
        if not (len(xs) == len(ys) == len(zs)):
            raise ValueError("waypoints_x/y/z parameters must be the same length")

        self._queue = WaypointQueue(
            waypoints=[Vector3(x, y, z) for x, y, z in zip(xs, ys, zs, strict=True)],
            tolerance_m=float(self.get_parameter("tolerance_m").value),
        )
        self._max_step_m = float(self.get_parameter("max_step_m").value)
        self._current_position = Vector3(0.0, 0.0, 0.0)
        self._have_position = False

        self._setpoint_pub = self.create_publisher(
            PoseStamped, "mavros/setpoint_position/local", 10
        )
        self.create_subscription(
            PoseStamped,
            "mavros/local_position/pose",
            self._on_local_position,
            QoSPresetProfiles.SENSOR_DATA.value,
        )
        self.create_subscription(
            PoseArray, "mission/waypoints", self._on_mission_waypoints, 10
        )

        self._arm_client = self.create_client(CommandBool, "mavros/cmd/arming")
        self._mode_client = self.create_client(SetMode, "mavros/set_mode")
        self._offboard_requested = False

        self.create_timer(CONTROL_PERIOD_S, self._on_control_tick)
        self.get_logger().info(
            f"waypoint_follower_node ready: {len(self._queue.waypoints)} waypoint(s)"
        )

    def _on_local_position(self, msg: PoseStamped) -> None:
        self._current_position = Vector3(
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z
        )
        self._have_position = True

    def _on_mission_waypoints(self, msg: PoseArray) -> None:
        waypoints = [Vector3(p.position.x, p.position.y, p.position.z) for p in msg.poses]
        if not waypoints:
            self.get_logger().warning("received empty mission/waypoints message, ignoring")
            return
        self._queue = WaypointQueue(waypoints=waypoints, tolerance_m=self._queue.tolerance_m)
        self._offboard_requested = False
        self.get_logger().info(f"mission received: {len(waypoints)} waypoint(s)")

    def _on_control_tick(self) -> None:
        if not self._have_position:
            return

        if self._queue.is_complete:
            return

        if not self._offboard_requested:
            self._request_offboard_and_arm()
            self._offboard_requested = True

        target = self._queue.step(self._current_position, self._max_step_m)
        self._publish_setpoint(target)

    def _publish_setpoint(self, target: Vector3) -> None:
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        msg.pose.position.x = target.x
        msg.pose.position.y = target.y
        msg.pose.position.z = target.z
        self._setpoint_pub.publish(msg)

    def _request_offboard_and_arm(self) -> None:
        # Best-effort, fire-and-forget: PX4 requires a steady stream of setpoints
        # before it accepts OFFBOARD, which the control timer above already provides.
        if self._mode_client.service_is_ready():
            req = SetMode.Request()
            req.custom_mode = "OFFBOARD"
            self._mode_client.call_async(req)
        if self._arm_client.service_is_ready():
            req = CommandBool.Request()
            req.value = True
            self._arm_client.call_async(req)


def main() -> None:
    rclpy.init()
    node = WaypointFollowerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
