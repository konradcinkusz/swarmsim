"""Launch file for M1/M2: one namespaced node set per swarm member.

    ros2 launch swarm_coordination spawn_swarm.launch.py mode:=waypoint drone_count:=3
    ros2 launch swarm_coordination spawn_swarm.launch.py \\
        mode:=formation drone_count:=4 formation_type:=v

`mode:=waypoint` (M1/M2 "podążanie za punktami trasy"): every drone runs a
`waypoint_follower_node`, each on the same path shifted by a per-drone X offset, so the
swarm moves as a group along parallel tracks rather than colliding on one line.

`mode:=formation` (M2 "formacja leader-follower"): drone 1 runs
`waypoint_follower_node` as the leader; drones 2..N run `formation_commander_node`,
each tracking drone 1's published position at its own offset in the chosen formation.

Also starts `mission_dispatcher_node` and `swarm_state_aggregator_node` — the two nodes
that make `POST /missions` / `GET /swarm/state` (M3) reach this swarm at runtime rather
than only the launch-time waypoint parameters above (M1/M2 manual testing).

Requires `mavros` running against each PX4 SITL instance's MAVLink endpoint — see
`swarm_coordination/README.md` for the companion `mavros` launch step this file does
not itself start (deliberately: MAVLink endpoint wiring is an infra concern, formation
logic is not, and conflating them would mean nobody can launch one without the other).
"""

from __future__ import annotations

from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from launch import LaunchDescription

WAYPOINT_ALTITUDE_M = 5.0
WAYPOINT_LEG_M = 10.0
LANE_SPACING_M = 3.0


def _waypoints_for_lane(drone_index: int) -> tuple[list[float], list[float], list[float]]:
    """A simple out-and-back path, one parallel lane per drone (M1's "z przesunięciem")."""
    y_offset = drone_index * LANE_SPACING_M
    xs = [0.0, WAYPOINT_LEG_M, WAYPOINT_LEG_M, 0.0]
    ys = [y_offset, y_offset, y_offset, y_offset]
    zs = [WAYPOINT_ALTITUDE_M] * 4
    return xs, ys, zs


def _launch_setup(context, *args, **kwargs):
    mode = LaunchConfiguration("mode").perform(context)
    drone_count = int(LaunchConfiguration("drone_count").perform(context))
    formation_type = LaunchConfiguration("formation_type").perform(context)
    spacing_m = LaunchConfiguration("spacing_m").perform(context)

    if drone_count < 1:
        raise ValueError("drone_count must be >= 1")
    if mode not in ("waypoint", "formation"):
        raise ValueError(f"unknown mode '{mode}', expected 'waypoint' or 'formation'")

    actions = []
    for i in range(1, drone_count + 1):
        namespace = f"drone_{i}"

        if mode == "waypoint" or i == 1:
            xs, ys, zs = _waypoints_for_lane(i - 1)
            actions.append(
                Node(
                    package="swarm_coordination",
                    executable="waypoint_follower_node",
                    namespace=namespace,
                    name="waypoint_follower_node",
                    parameters=[
                        {
                            "waypoints_x": xs,
                            "waypoints_y": ys,
                            "waypoints_z": zs,
                        }
                    ],
                )
            )
        else:
            actions.append(
                Node(
                    package="swarm_coordination",
                    executable="formation_commander_node",
                    namespace=namespace,
                    name="formation_commander_node",
                    parameters=[
                        {
                            "formation_type": formation_type,
                            "follower_count": drone_count - 1,
                            "follower_index": i - 2,
                            "spacing_m": float(spacing_m),
                            "leader_position_topic": "/drone_1/mavros/local_position/pose",
                        }
                    ],
                )
            )

    actions.append(
        Node(
            package="swarm_coordination",
            executable="mission_dispatcher_node",
            name="mission_dispatcher_node",
        )
    )
    actions.append(
        Node(
            package="swarm_coordination",
            executable="swarm_state_aggregator_node",
            name="swarm_state_aggregator_node",
            parameters=[{"drone_count": drone_count}],
        )
    )

    return actions


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "mode", default_value="waypoint", description="'waypoint' or 'formation'"
            ),
            DeclareLaunchArgument(
                "drone_count", default_value="3", description="Number of swarm members (M1: 3-5)"
            ),
            DeclareLaunchArgument(
                "formation_type",
                default_value="line",
                description="'line' or 'v' (mode=formation only)",
            ),
            DeclareLaunchArgument(
                "spacing_m", default_value="2.0", description="Formation spacing in meters"
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
