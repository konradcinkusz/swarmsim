"""The scenario instrument: swarm scenarios as data, run against a system under test.

A scenario (YAML, validated against contracts/scenario/scenario.v1.schema.json) is a
world, a timeline of events — missions, operator commands, injected faults — and the
assertions to hold the swarm to. ``run_scenario(spec, sut, seed)`` flies it in L0, a
seeded kinematic simulation (``sim.py``), against a system under test (``sut.py``): this
repository's own swarm software by default, or anyone's that implements the protocol.
The result is a ``Verdict`` — measured, time-stamped violations — and the ``Trace`` it
was read from.

    python -m swarm_coordination.scenarios run scenarios/ --seeds 3 --mutants

The mutation check (``mutants.py``) runs every scenario against deliberately broken
swarms: a scenario no mutant fails is reported as toothless.
"""

from .harness import run_scenario
from .model import AssertionOutcome, Frame, Trace, Verdict, Violation
from .runner import SuiteReport, run_suite
from .spec import ScenarioError, ScenarioSpec, load_scenario, parse_scenario
from .sut import ReferenceSwarm, SystemUnderTest

__all__ = [
    "AssertionOutcome",
    "Frame",
    "ReferenceSwarm",
    "ScenarioError",
    "ScenarioSpec",
    "SuiteReport",
    "SystemUnderTest",
    "Trace",
    "Verdict",
    "Violation",
    "load_scenario",
    "parse_scenario",
    "run_scenario",
    "run_suite",
]
