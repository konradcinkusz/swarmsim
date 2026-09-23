"""ROS 2 node: the swarm's single runtime entry point for missions and commands.

Subscribes to `/swarm/mission` and `/swarm/command` — JSON in a `std_msgs/String`, the
payloads in contracts/rosbridge/ that `SwarmApi.Infrastructure.RosBridgeSwarmBridge`
publishes over rosbridge — and to every drone's battery and mission progress. What to do
with them is decided by the rclpy-free `supervisor.MissionSupervisor`: which drones fly a
mission, and which drone takes over when one runs low on battery. This node only carries
its decisions out: a path on `/<drone>/mission/assignment`, a place behind the leader on
`/<drone>/mission/slot`, a command on `/<drone>/mission/command`, and the current
mission and its drones latched on `/swarm/active_mission` for the state aggregator.
"""

from __future__ import annotations

import json

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String

from ..mission_planning import parse_command_payload, parse_mission_payload
from ..supervisor import (
    ActiveMission,
    Assign,
    Command,
    MissionSupervisor,
    Rejected,
    Slot,
    TaskDropped,
)
from ..swarm_state import battery_percent

LATCHED = QoSProfile(
    depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE
)
REALLOCATION_PERIOD_S = 1.0


class MissionDispatcherNode(Node):
    def __init__(self) -> None:
        super().__init__("mission_dispatcher_node")
        self.declare_parameter("drones", ["drone_1"])
        self.declare_parameter("battery_threshold_pct", 20.0)
        self._drones = [str(d) for d in self.get_parameter("drones").value]
        self._supervisor = MissionSupervisor(
            self._drones, float(self.get_parameter("battery_threshold_pct").value)
        )

        # Every drone's publishers exist from the start, not from the first mission: a
        # publisher created just before its first message may not be matched with its
        # subscribers yet, and a volatile message sent then is lost. Not in
        # `self._publishers`: rclpy.node.Node keeps its own list there, and replacing it
        # killed this node at start in every SITL smoke run that started it, until
        # 2026-09-22.
        self._topic_publishers: dict[str, object] = {}
        for drone in self._drones:
            for topic in ("mission/assignment", "mission/slot", "mission/command"):
                self._publisher(f"/{drone}/{topic}")
        self._active_pub = self.create_publisher(String, "/swarm/active_mission", LATCHED)
        self.create_subscription(String, "/swarm/mission", self._on_mission, 10)
        self.create_subscription(String, "/swarm/command", self._on_command, 10)
        for drone in self._drones:
            self.create_subscription(
                BatteryState,
                f"/{drone}/mavros/battery",
                self._on_battery(drone),
                qos_profile_sensor_data,
            )
            self.create_subscription(
                String, f"/{drone}/mission/progress", self._on_progress(drone), 10
            )
        self.create_timer(REALLOCATION_PERIOD_S, self._reallocate)
        self._carry_out([ActiveMission(None, ())])
        self.get_logger().info(f"mission_dispatcher_node ready for {self._drones}")

    def _publisher(self, topic: str):
        if topic not in self._topic_publishers:
            self._topic_publishers[topic] = self.create_publisher(String, topic, 10)
        return self._topic_publishers[topic]

    def _send(self, topic: str, payload) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self._publisher(topic).publish(String(data=text))

    # --- what the swarm and the operator say --------------------------------------------

    def _on_mission(self, msg: String) -> None:
        try:
            mission = parse_mission_payload(msg.data)
        except ValueError as exc:
            self.get_logger().error(f"rejected /swarm/mission: {exc}")
            return
        self._carry_out(self._supervisor.start(mission))

    def _on_command(self, msg: String) -> None:
        try:
            command = parse_command_payload(msg.data)
        except ValueError as exc:
            self.get_logger().error(f"rejected /swarm/command: {exc}")
            return
        self._carry_out(self._supervisor.command(command))
        self.get_logger().warning(f"swarm command '{command.command}' sent to {self._drones}")

    def _on_battery(self, drone: str):
        def handler(msg: BatteryState) -> None:
            self._supervisor.observe_battery(drone, battery_percent(msg.percentage))

        return handler

    def _on_progress(self, drone: str):
        def handler(msg: String) -> None:
            try:
                progress = json.loads(msg.data)
                self._supervisor.observe_progress(
                    drone,
                    progress.get("mission_id"),
                    progress.get("waypoint_index"),
                    bool(progress.get("complete")),
                )
            except (ValueError, AttributeError):
                return

        return handler

    def _reallocate(self) -> None:
        self._carry_out(self._supervisor.reallocate())

    # --- what the supervisor decided ----------------------------------------------------

    def _carry_out(self, actions) -> None:
        for action in actions:
            if isinstance(action, Assign):
                self._send(
                    f"/{action.drone}/mission/assignment",
                    {
                        "mission_id": action.mission_id,
                        "waypoints": [[w.x, w.y, w.z] for w in action.waypoints],
                    },
                )
            elif isinstance(action, Slot):
                offset = action.offset
                self._send(
                    f"/{action.drone}/mission/slot",
                    {
                        "mission_id": action.mission_id,
                        "leader": action.leader,
                        "offset": [offset.x, offset.y, offset.z],
                    },
                )
            elif isinstance(action, Command):
                self._send(f"/{action.drone}/mission/command", action.command)
            elif isinstance(action, ActiveMission):
                payload = {"mission_id": action.mission_id, "drones": list(action.drones)}
                self._active_pub.publish(String(data=json.dumps(payload)))
                if action.mission_id is not None:
                    self.get_logger().info(
                        f"mission {action.mission_id} flown by {list(action.drones)}"
                    )
            elif isinstance(action, Rejected):
                self.get_logger().error(f"rejected mission {action.mission_id}: {action.reason}")
            elif isinstance(action, TaskDropped):
                self.get_logger().error(
                    f"{action.drone} sent home, its task in mission {action.mission_id} "
                    f"dropped: {action.reason}"
                )


def main() -> None:
    rclpy.init()
    node = MissionDispatcherNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
