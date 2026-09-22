import pytest

from swarm_coordination.commands import mode_for_command


@pytest.mark.parametrize(
    ("command", "mode"), [("rtl", "AUTO.RTL"), ("land", "AUTO.LAND"), ("hold", "AUTO.LOITER")]
)
def test_every_swarm_command_is_a_px4_autonomous_mode(command, mode):
    assert mode_for_command(command) == mode


def test_an_unknown_command_is_rejected():
    with pytest.raises(ValueError):
        mode_for_command("self_destruct")
