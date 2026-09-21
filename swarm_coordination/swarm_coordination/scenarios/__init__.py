"""The scenario-testing contract: the shape every swarm-testing-as-a-service scenario
implements against.

A ``Scenario`` is a named, self-contained test case — it owns its own setup and
perturbation internally, so evaluating it is nothing more than calling ``run()``.
Running it produces a ``Verdict``: pass/fail plus, on failure, the concrete
``Violation``\\ s a future report/replay layer will render.

This module is deliberately just the contract (dataclasses + a ``Protocol``), with no
registry. Scenario implementations live in sibling modules (see
``example_static_formation.py``) that only import from here, so multiple engineers can
each add a scenario module in parallel without contending on a shared file. A light,
*non-enforced* convention for future auto-discovery: a scenario module may export a
module-level ``SCENARIO = Scenario(...)`` constant, so a future collector could glob
``scenarios/*.py`` and pick that up — nothing in this package requires it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Violation:
    """A single concrete, reportable fact about a scenario failure.

    ``drone_ids`` holds every drone involved (one id for a single-drone fault, two for
    e.g. a separation breach between a pair). ``measured_value`` and ``threshold`` are
    in the same unit (e.g. metres for a separation check) so a report can show both.
    """

    drone_ids: list[str]
    timestamp_s: float
    measured_value: float
    threshold: float
    description: str


@dataclass(frozen=True)
class Verdict:
    """The result of running a ``Scenario``: pass/fail plus why, if it failed.

    ``violations`` is empty exactly when ``passed`` is True.
    """

    passed: bool
    violations: list[Violation] = field(default_factory=list)


@dataclass(frozen=True)
class Scenario:
    """A named, described, self-contained test case.

    ``run`` takes no arguments — the scenario owns its own setup and perturbation
    internally, so a caller (or future test harness) evaluates it with nothing but
    ``scenario.run()``.
    """

    name: str
    description: str
    run: Callable[[], Verdict]
