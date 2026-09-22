"""Launch the swarm's ROS 2 side for the drones PX4 SITL is running.

    ros2 launch swarm_coordination spawn_swarm.launch.py with_mavros:=true
    ros2 launch swarm_coordination spawn_swarm.launch.py drone_count:=3 \\
        px4_config_dir:=/path/to/simulation/px4-configs

The drones are read from simulation/px4-configs/drone_<n>.env — the same files
docker/entrypoint.sh starts PX4 from — so every drone's namespace, MAVLink ports (from
its PX4 instance index) and spawn offset (its local frame's origin in the world) have one
source of truth. Per drone this starts a `drone_controller_node` and, with
`with_mavros:=true`, the MAVROS bridge to that PX4 instance. Once for the swarm it starts
`mission_dispatcher_node` and `swarm_state_aggregator_node`.

Nothing flies until a mission arrives on /swarm/mission — from SwarmApi.Api over
rosbridge, or by hand:

    ros2 topic pub --once /swarm/mission std_msgs/String \\
        "{data: '$(cat contracts/rosbridge/examples/swarm_mission.json | tr -d \\\\n)'}"
"""

from __future__ import annotations

import os

from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from launch import LaunchDescription
from swarm_coordination.px4_config import load_drone_configs

DEFAULT_CONFIG_DIR = os.environ.get("SWARMSIM_PX4_CONFIG_DIR", "/opt/swarmsim/px4-configs")


def _truthy(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "yes")


def _mavros_parameter_files() -> list[str]:
    # Imported here so the launch file loads (and --show-args works) without MAVROS.
    from ament_index_python.packages import get_package_share_directory

    share = get_package_share_directory("mavros")
    return [
        os.path.join(share, "launch", "px4_pluginlists.yaml"),
        os.path.join(share, "launch", "px4_config.yaml"),
    ]


def _launch_setup(context, *args, **kwargs):
    config_dir = LaunchConfiguration("px4_config_dir").perform(context)
    count_text = LaunchConfiguration("drone_count").perform(context).strip()
    with_mavros = _truthy(LaunchConfiguration("with_mavros").perform(context))

    configs = load_drone_configs(config_dir, int(count_text) if count_text else None)
    mavros_files = _mavros_parameter_files() if with_mavros else []

    actions = []
    for config in configs:
        if with_mavros:
            # No `name=`: it would remap every node in the mavros process, including each
            # plugin's own node. Topics come out as /<drone>/mavros/state and so on.
            actions.append(
                Node(
                    package="mavros",
                    executable="mavros_node",
                    namespace=config.namespace,
                    output="screen",
                    parameters=[
                        *mavros_files,
                        {
                            "fcu_url": config.fcu_url,
                            "gcs_url": "",
                            "tgt_system": config.system_id,
                            "tgt_component": 1,
                            "fcu_protocol": "v2.0",
                        },
                    ],
                )
            )
        actions.append(
            Node(
                package="swarm_coordination",
                executable="drone_controller_node",
                namespace=config.namespace,
                name="drone_controller_node",
                output="screen",
                parameters=[
                    {
                        "spawn_x": config.spawn.x,
                        "spawn_y": config.spawn.y,
                        "spawn_z": config.spawn.z,
                    }
                ],
            )
        )

    drones = [config.namespace for config in configs]
    actions.append(
        Node(
            package="swarm_coordination",
            executable="mission_dispatcher_node",
            name="mission_dispatcher_node",
            output="screen",
            parameters=[{"drones": drones}],
        )
    )
    actions.append(
        Node(
            package="swarm_coordination",
            executable="swarm_state_aggregator_node",
            name="swarm_state_aggregator_node",
            output="screen",
            parameters=[{"drones": drones}],
        )
    )
    return actions


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "px4_config_dir",
                default_value=DEFAULT_CONFIG_DIR,
                description="Directory holding x500_common.env and drone_<n>.env",
            ),
            DeclareLaunchArgument(
                "drone_count",
                default_value=os.environ.get("SWARM_DRONE_COUNT", ""),
                description="Use only the first N drone configs (empty: all of them)",
            ),
            DeclareLaunchArgument(
                "with_mavros",
                default_value="false",
                description="Also start one MAVROS bridge per drone",
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
