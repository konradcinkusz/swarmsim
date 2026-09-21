"""Reference scenario: a formation holding position with zero perturbation.

Deliberately trivial and boring — it exists to demonstrate the ``Scenario`` contract
end to end, not to exercise anything interesting about formation-keeping. It always
passes. (Formation-hold *under GPS noise* is a separate, non-trivial scenario tracked
as its own piece of work — this one stays static on purpose so the two don't overlap.)
"""

from __future__ import annotations

from ..formation import follower_targets, min_separation, v_formation
from ..trajectory import Vector3
from . import Scenario, Verdict, Violation

_MIN_SEPARATION_M = 1.0


def _run() -> Verdict:
    """Hold a 4-follower V formation at a fixed leader position and check separation.

    No perturbation is applied between setup and evaluation, so the followers are
    exactly at their commanded offsets — this should always pass.
    """
    leader = Vector3(0.0, 0.0, 5.0)
    offsets = v_formation(count=4, spacing_m=2.0)
    positions = [leader, *follower_targets(leader, offsets)]

    separation = min_separation(positions)
    if separation is not None and separation < _MIN_SEPARATION_M:
        violation = Violation(
            drone_ids=["leader", "follower"],
            timestamp_s=0.0,
            measured_value=separation,
            threshold=_MIN_SEPARATION_M,
            description="static V formation violated minimum separation",
        )
        return Verdict(passed=False, violations=[violation])
    return Verdict(passed=True)


SCENARIO = Scenario(
    name="static_formation_holds",
    description=(
        "A 4-follower V formation held at a fixed position with zero perturbation; "
        "always passes. Reference implementation of the Scenario contract."
    ),
    run=_run,
)
