"""ROS 2 node: one drone's controller — the thin adapter around drone_controller.DroneController.

One instance per drone, in that drone's namespace (see `launch/spawn_swarm.launch.py`).
It converts between the drone's own local frame (what MAVROS speaks) and the shared world
frame (what missions and the swarm state use) with the drone's spawn offset and its home
height (`frames.py` says why heights are measured from home), feeds MAVROS
readings to the controller, and carries out what the controller decides: publish a
setpoint, ask PX4 for a mode, ask it to arm. Every decision is in the rclpy-free
`drone_controller.py` / `offboard.py`, unit tested without ROS.

Topics, relative to the drone's namespace (e.g. /drone_2):
  in   mavros/local_position/pose  PoseStamped, local ENU
       mavros/state                mavros_msgs/State
       mavros/home_position/home   mavros_msgs/HomePosition, local ENU (latched)
       mission/assignment          String JSON {"mission_id", "waypoints": [[x, y, z], ...]} (world)
       mission/slot                String JSON {"mission_id", "leader", "offset": [x, y, z]} (world)
       mission/command             String "rtl" | "land" | "hold"
       /<leader>/world_pose, /<leader>/mission/progress   while following a leader
  out  mavros/setpoint_position/local  PoseStamped, local ENU
       world_pose                      PoseStamped, world ENU
       mission/progress                String JSON (drone_controller.Progress)
"""

from __future__ import annotations

import json

import rclpy
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import HomePosition, State
from mavros_msgs.srv import CommandBool, SetMode
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from std_msgs.msg import String

from ..drone_controller import DroneController
from ..frames import local_to_world, world_to_local
from ..trajectory import Vector3

CONTROL_RATE_HZ = 10.0
# MAVROS publishes home latched (reliable, transient local): subscribing the same way
# delivers the last home at once instead of waiting for PX4 to send it again.
HOME_QOS = QoSProfile(
    depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE
)


def _vector(msg: PoseStamped) -> Vector3:
    p = msg.pose.position
    return Vector3(p.x, p.y, p.z)


def _pose(v: Vector3, frame_id: str, stamp) -> PoseStamped:
    msg = PoseStamped()
    msg.header.stamp = stamp
    msg.header.frame_id = frame_id
    msg.pose.position.x = v.x
    msg.pose.position.y = v.y
    msg.pose.position.z = v.z
    msg.pose.orientation.w = 1.0
    return msg


class DroneControllerNode(Node):
    def __init__(self) -> None:
        super().__init__("drone_controller_node")

        self.declare_parameter("spawn_x", 0.0)
        self.declare_parameter("spawn_y", 0.0)
        self.declare_parameter("spawn_z", 0.0)
        self.declare_parameter("max_step_m", 2.0)
        self.declare_parameter("tolerance_m", 0.5)
        self._spawn = Vector3(
            float(self.get_parameter("spawn_x").value),
            float(self.get_parameter("spawn_y").value),
            float(self.get_parameter("spawn_z").value),
        )
        self._drone_id = self.get_namespace().strip("/") or "drone"
        self._controller = DroneController(
            self._drone_id,
            tolerance_m=float(self.get_parameter("tolerance_m").value),
            max_step_m=float(self.get_parameter("max_step_m").value),
            warmup_ticks=int(CONTROL_RATE_HZ * 2),  # PX4 wants ~2 s of setpoints first
            retry_interval_s=1.0,
        )

        self._position: Vector3 | None = None
        self._home_height: float | None = None  # local z of PX4's home; None until reported
        self._armed: bool | None = None
        self._mode: str | None = None
        self._leader: str | None = None
        self._leader_position: Vector3 | None = None
        self._leader_subscriptions: list = []
        self._last_progress: str | None = None

        self._setpoint_pub = self.create_publisher(
            PoseStamped, "mavros/setpoint_position/local", 10
        )
        self._world_pose_pub = self.create_publisher(PoseStamped, "world_pose", 10)
        self._progress_pub = self.create_publisher(String, "mission/progress", 10)

        # Best-effort subscriptions match MAVROS whatever reliability it publishes with.
        self.create_subscription(
            PoseStamped, "mavros/local_position/pose", self._on_local_pose, qos_profile_sensor_data
        )
        self.create_subscription(State, "mavros/state", self._on_state, qos_profile_sensor_data)
        self.create_subscription(HomePosition, "mavros/home_position/home", self._on_home, HOME_QOS)
        self.create_subscription(String, "mission/assignment", self._on_assignment, 10)
        self.create_subscription(String, "mission/slot", self._on_slot, 10)
        self.create_subscription(String, "mission/command", self._on_command, 10)

        self._arm_client = self.create_client(CommandBool, "mavros/cmd/arming")
        self._mode_client = self.create_client(SetMode, "mavros/set_mode")
        self._last_warning_s: dict[str, float] = {}

        self.create_timer(1.0 / CONTROL_RATE_HZ, self._on_tick)
        self.create_timer(1.0, self._republish_progress)
        self.get_logger().info(
            f"drone_controller_node ready for {self._drone_id}, spawn offset {self._spawn}"
        )

    # --- MAVROS readings ---------------------------------------------------------------

    def _on_local_pose(self, msg: PoseStamped) -> None:
        self._position = local_to_world(_vector(msg), self._spawn, self._home_height or 0.0)
        self._world_pose_pub.publish(_pose(self._position, "world", msg.header.stamp))

    def _on_home(self, msg: HomePosition) -> None:
        if self._home_height is None:
            self.get_logger().info(
                f"home at local height {msg.position.z:.2f} m; heights are measured from it"
            )
        self._home_height = float(msg.position.z)

    def _on_state(self, msg: State) -> None:
        self._armed = bool(msg.armed)
        self._mode = str(msg.mode)

    # --- tasks from the dispatcher -----------------------------------------------------

    def _on_assignment(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
            waypoints = [Vector3(*(float(c) for c in wp)) for wp in payload["waypoints"]]
            self._controller.assign_path(str(payload["mission_id"]), waypoints)
        except (KeyError, TypeError, ValueError) as exc:
            self.get_logger().error(f"rejected malformed mission/assignment: {exc}")
            return
        self._follow(None)
        self.get_logger().info(f"path assigned: {len(waypoints)} waypoint(s)")

    def _on_slot(self, msg: String) -> None:
        try:
            payload = json.loads(msg.data)
            offset = Vector3(*(float(c) for c in payload["offset"]))
            leader = str(payload["leader"])
            self._controller.assign_slot(str(payload["mission_id"]), leader, offset)
        except (KeyError, TypeError, ValueError) as exc:
            self.get_logger().error(f"rejected malformed mission/slot: {exc}")
            return
        self._follow(leader)
        self.get_logger().info(f"following {leader} at offset {offset}")

    def _on_command(self, msg: String) -> None:
        try:
            self._controller.command(msg.data.strip())
        except ValueError as exc:
            self.get_logger().error(str(exc))
            return
        self._follow(None)
        self.get_logger().warning(f"swarm command '{msg.data.strip()}': handing over to PX4")

    def _follow(self, leader: str | None) -> None:
        if leader == self._leader:
            return
        for subscription in self._leader_subscriptions:
            self.destroy_subscription(subscription)
        self._leader_subscriptions = []
        self._leader = leader
        self._leader_position = None
        if leader is None:
            return
        self._leader_subscriptions = [
            self.create_subscription(
                PoseStamped, f"/{leader}/world_pose", self._on_leader_pose, 10
            ),
            self.create_subscription(
                String, f"/{leader}/mission/progress", self._on_leader_progress, 10
            ),
        ]

    def _on_leader_pose(self, msg: PoseStamped) -> None:
        self._leader_position = _vector(msg)

    def _on_leader_progress(self, msg: String) -> None:
        try:
            progress = json.loads(msg.data)
        except ValueError:
            return
        if progress.get("complete") and progress.get("mission_id"):
            self._controller.leader_finished(str(progress["mission_id"]))

    # --- the control loop --------------------------------------------------------------

    def _on_tick(self) -> None:
        now = self.get_clock().now()
        out = self._controller.tick(
            now.nanoseconds * 1e-9, self._position, self._armed, self._mode, self._leader_position
        )
        if out.setpoint is not None:
            local = world_to_local(out.setpoint, self._spawn, self._home_height or 0.0)
            self._setpoint_pub.publish(_pose(local, "map", now.to_msg()))
        if out.request_mode is not None:
            request = SetMode.Request()
            request.custom_mode = out.request_mode
            self._ask(self._mode_client, "mavros/set_mode", request, out.request_mode, _mode_sent)
        if out.request_arm:
            request = CommandBool.Request()
            request.value = True
            self._ask(self._arm_client, "mavros/cmd/arming", request, "arming", _arm_accepted)
        self._publish_progress(only_if_changed=True)

    def _ask(self, client, service: str, request, what: str, accepted) -> None:
        """One request to PX4 through MAVROS. The sequencer repeats it once a second until
        PX4's reported state says it happened, so each attempt and each refusal is logged:
        a drone that never takes off says why."""
        if not client.service_is_ready():
            self._warn_every(5.0, service, f"cannot ask PX4 for {what}: {service} is not available")
            return
        self.get_logger().info(f"asking PX4 for {what}")
        client.call_async(request).add_done_callback(
            lambda future: self._on_answer(future, what, accepted)
        )

    def _on_answer(self, future, what: str, accepted) -> None:
        try:
            response = future.result()
        except Exception as exc:  # noqa: BLE001 - any failure of the call is worth a line
            self._warn_every(5.0, what, f"request for {what} failed: {exc}")
            return
        if not accepted(response):
            self._warn_every(5.0, what, f"PX4 refused {what}: {response}")

    def _warn_every(self, period_s: float, key: str, text: str) -> None:
        now_s = self.get_clock().now().nanoseconds * 1e-9
        if now_s - self._last_warning_s.get(key, float("-inf")) >= period_s:
            self._last_warning_s[key] = now_s
            self.get_logger().warning(text)

    def _republish_progress(self) -> None:
        self._publish_progress(only_if_changed=False)

    def _publish_progress(self, only_if_changed: bool) -> None:
        data = json.dumps(self._controller.progress.as_dict())
        if only_if_changed and data == self._last_progress:
            return
        self._last_progress = data
        self._progress_pub.publish(String(data=data))


def _mode_sent(response) -> bool:
    return bool(getattr(response, "mode_sent", False))


def _arm_accepted(response) -> bool:
    return bool(getattr(response, "success", False))


def main() -> None:
    rclpy.init()
    node = DroneControllerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
