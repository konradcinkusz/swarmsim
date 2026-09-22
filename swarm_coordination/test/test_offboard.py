import pytest

from swarm_coordination.offboard import OffboardSequencer, Phase


def _run(seq, ticks, armed=False, mode="POSCTL", start_s=0.0, dt=0.1):
    steps = []
    for i in range(ticks):
        steps.append(seq.step(start_s + i * dt, armed, mode))
    return steps


def test_idle_until_started():
    seq = OffboardSequencer()

    assert seq.step(0.0, False, "POSCTL").stream_setpoint is False


def test_streams_setpoints_before_asking_for_offboard():
    seq = OffboardSequencer(warmup_ticks=5)
    seq.start()

    warmup = _run(seq, 5)

    assert all(s.stream_setpoint for s in warmup)
    assert not any(s.request_offboard or s.request_arm for s in warmup)
    assert seq.phase == Phase.REQUEST_MODE


def test_asks_for_offboard_at_the_retry_interval_not_every_tick():
    seq = OffboardSequencer(warmup_ticks=1, retry_interval_s=1.0)
    seq.start()
    seq.step(0.0, False, "POSCTL")

    requests = [s.request_offboard for s in _run(seq, 25, start_s=0.1)]  # 2.5 s at 10 Hz

    assert requests.count(True) == 3  # at 0.1 s, 1.1 s and 2.1 s
    assert requests[0] is True


def test_arms_once_offboard_is_reported_then_goes_active():
    seq = OffboardSequencer(warmup_ticks=1)
    seq.start()
    seq.step(0.0, False, "POSCTL")

    arming = seq.step(0.1, False, "OFFBOARD")
    active = seq.step(0.2, True, "OFFBOARD")

    assert arming.request_arm is True and arming.stream_setpoint is True
    assert seq.phase == Phase.ACTIVE
    assert active.stream_setpoint is True and not active.request_arm


def test_does_not_trust_a_request_before_px4_reports_the_result():
    seq = OffboardSequencer(warmup_ticks=1, retry_interval_s=0.5)
    seq.start()
    seq.step(0.0, False, None)

    # MAVROS has not reported any state yet: keep streaming, keep asking.
    steps = _run(seq, 20, armed=None, mode=None, start_s=0.1)

    assert all(s.stream_setpoint for s in steps)
    assert sum(s.request_offboard for s in steps) >= 3
    assert seq.phase == Phase.REQUEST_MODE


def test_lets_go_when_px4_leaves_offboard_on_its_own():
    seq = OffboardSequencer(warmup_ticks=1)
    seq.start()
    seq.step(0.0, False, "POSCTL")
    seq.step(0.1, False, "OFFBOARD")
    seq.step(0.2, True, "OFFBOARD")

    step = seq.step(0.3, True, "AUTO.RTL")  # a failsafe, or a pilot

    assert step.stream_setpoint is False
    assert seq.phase == Phase.RELEASED
    assert seq.step(0.4, True, "OFFBOARD").stream_setpoint is False


def test_start_resets_a_released_sequencer():
    seq = OffboardSequencer(warmup_ticks=2)
    seq.release()
    seq.start()

    assert seq.phase == Phase.WARMUP


def test_warmup_must_be_positive():
    with pytest.raises(ValueError):
        OffboardSequencer(warmup_ticks=0)
