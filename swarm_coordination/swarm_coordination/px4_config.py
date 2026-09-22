"""Reads simulation/px4-configs/drone_<n>.env — the one source of truth for the swarm.

PX4 SITL is started from these files (docker/entrypoint.sh), so the ROS 2 side reads the
same files instead of repeating the numbers: each drone's namespace, its PX4 instance
index (which fixes its MAVLink ports and system id), and its spawn pose (its local-frame
origin in the world). No rclpy: unit tested without ROS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .frames import parse_model_pose
from .trajectory import Vector3

_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")

# The MAVROS plugins each drone's bridge loads, and what each gives the nodes. Left to
# itself MAVROS loads every plugin it ships — parameter and mission sync on connect, IMU
# and GPS streams — on every drone, and with three drones, PX4, Gazebo and MAVROS on a
# 4-CPU runner, MAVROS's time-sync round trip reached 1.3 s. A topic or service used
# without its plugin is never served and fails silently, so test_px4_config.py checks
# every MAVROS name the nodes use against this table.
MAVROS_PLUGINS: dict[str, tuple[str, ...]] = {
    "sys_status": ("mavros/state", "mavros/battery", "mavros/set_mode"),
    "command": ("mavros/cmd/arming",),
    "local_position": ("mavros/local_position/pose",),
    "setpoint_position": ("mavros/setpoint_position/local",),
    "home_position": ("mavros/home_position/home",),
    "sys_time": (),  # keeps MAVROS's clock in step with PX4's
}


@dataclass(frozen=True)
class DroneConfig:
    namespace: str
    instance: int
    spawn: Vector3

    @property
    def system_id(self) -> int:
        """MAV_SYS_ID — PX4 sets it to instance + 1 (init.d-posix/rcS)."""
        return self.instance + 1

    @property
    def fcu_url(self) -> str:
        """MAVROS's link to this PX4 instance's onboard MAVLink port (px4-rc.mavlink)."""
        return f"udp://:{14540 + self.instance}@127.0.0.1:{14580 + self.instance}"


def parse_env(text: str) -> dict[str, str]:
    """KEY=value lines; blank lines and # comments ignored; optional quotes stripped."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            raise ValueError(f"not a KEY=value line: {line!r}")
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_drone_configs(config_dir: str | Path, count: int | None = None) -> list[DroneConfig]:
    """Every drone_<n>.env in ``config_dir``, in numeric order, optionally the first ``count``."""
    directory = Path(config_dir)
    common = directory / "x500_common.env"
    base = parse_env(common.read_text()) if common.exists() else {}

    def number(path: Path) -> int:
        return int(path.stem.split("_", 1)[1])

    files = sorted(directory.glob("drone_*.env"), key=number)
    if not files:
        raise FileNotFoundError(f"no drone_*.env in {directory}")
    if count is not None:
        if not 1 <= count <= len(files):
            raise ValueError(f"count must be between 1 and {len(files)}, got {count}")
        files = files[:count]

    configs = []
    for path in files:
        values = {**base, **parse_env(path.read_text())}
        try:
            configs.append(
                DroneConfig(
                    namespace=values["ROS_NAMESPACE"],
                    instance=int(values["PX4_INSTANCE"]),
                    spawn=parse_model_pose(values["PX4_GZ_MODEL_POSE"]),
                )
            )
        except KeyError as missing:
            raise ValueError(f"{path.name} is missing {missing}") from None
    return configs


def spawn_offsets(configs: list[DroneConfig]) -> dict[str, Vector3]:
    return {config.namespace: config.spawn for config in configs}
