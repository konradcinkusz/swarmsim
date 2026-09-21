import os
from glob import glob

from setuptools import find_packages, setup

package_name = "swarm_coordination"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Konrad Cinkusz",
    maintainer_email="konradcinkusz@gmail.com",
    description=(
        "Waypoint-following and leader-follower formation coordination for a "
        "multi-drone swarm."
    ),
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "waypoint_follower_node = swarm_coordination.nodes.waypoint_follower_node:main",
            "formation_commander_node = swarm_coordination.nodes.formation_commander_node:main",
            "mission_dispatcher_node = "
            "swarm_coordination.nodes.mission_dispatcher_node:main",
            "swarm_state_aggregator_node = "
            "swarm_coordination.nodes.swarm_state_aggregator_node:main",
        ],
    },
)
