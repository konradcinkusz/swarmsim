import re
from pathlib import Path

import pytest

from swarm_coordination.px4_config import (
    MAVROS_PLUGINS,
    load_drone_configs,
    parse_env,
    spawn_offsets,
)
from swarm_coordination.trajectory import Vector3

REPO_CONFIGS = Path(__file__).resolve().parents[2] / "simulation" / "px4-configs"


def test_parse_env_ignores_comments_and_strips_quotes():
    values = parse_env("# comment\n\nA=1\nB = \"two words\"\nC='x'\n")

    assert values == {"A": "1", "B": "two words", "C": "x"}


def test_parse_env_rejects_a_line_that_is_not_key_value():
    with pytest.raises(ValueError):
        parse_env("export A=1\n")


def test_the_committed_configs_describe_five_drones_three_metres_apart():
    configs = load_drone_configs(REPO_CONFIGS)

    assert [c.namespace for c in configs] == [f"drone_{n}" for n in range(1, 6)]
    assert [c.instance for c in configs] == [0, 1, 2, 3, 4]
    assert spawn_offsets(configs)["drone_3"] == Vector3(0.0, 6.0, 0.0)


def test_ports_and_system_id_follow_the_instance_as_px4_derives_them():
    drone_2 = load_drone_configs(REPO_CONFIGS)[1]

    assert drone_2.system_id == 2
    assert drone_2.fcu_url == "udp://:14541@127.0.0.1:14581"


def test_count_takes_the_first_n_in_numeric_order(tmp_path):
    for n in (1, 2, 10):
        (tmp_path / f"drone_{n}.env").write_text(
            f"PX4_INSTANCE={n - 1}\nROS_NAMESPACE=drone_{n}\nPX4_GZ_MODEL_POSE=0,{n},0\n"
        )

    configs = load_drone_configs(tmp_path, count=2)

    assert [c.namespace for c in configs] == ["drone_1", "drone_2"]
    with pytest.raises(ValueError):
        load_drone_configs(tmp_path, count=4)


def test_a_config_missing_a_variable_names_it(tmp_path):
    (tmp_path / "drone_1.env").write_text("PX4_INSTANCE=0\nROS_NAMESPACE=drone_1\n")

    with pytest.raises(ValueError, match="PX4_GZ_MODEL_POSE"):
        load_drone_configs(tmp_path)


def test_no_configs_at_all_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_drone_configs(tmp_path)


def test_every_mavros_name_the_nodes_use_comes_from_a_loaded_plugin():
    nodes = Path(__file__).resolve().parents[1] / "swarm_coordination" / "nodes"
    used = {
        name
        for source in nodes.glob("*.py")
        for name in re.findall(r"mavros/[a-z_]+(?:/[a-z_]+)*", source.read_text())
    }
    provided = {name for names in MAVROS_PLUGINS.values() for name in names}

    assert used, "the node sources name no MAVROS topic at all: the scan is broken"
    assert used <= provided, f"no loaded MAVROS plugin serves {sorted(used - provided)}"
