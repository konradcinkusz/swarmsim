"""Which scenarios the swarm under test is expected to fail, and why.

A scenario file's ``expect: fail`` is a statement about one swarm: this repository's
reference swarm. Another swarm flown against the same scenarios has limitations of its
own, and may have closed the reference's, so whether a failure is a regression or a known
gap belongs to the (scenario, swarm) pair, not to the scenario file.

An expectations file says it for one swarm (YAML,
contracts/scenario/expectations.v1.schema.json): the scenarios it is expected to fail, each
with a reason. With one, the scenario files' own ``expect`` is ignored. A scenario named in
it must fail and every other must pass, so a swarm that fixes a reference limitation is held
to the fix, and a limitation of its own is written down where its authors keep it.

PyYAML and jsonschema are needed here, as for the scenario files.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from .spec import ScenarioError, ScenarioSpec, check_against_schema, read_mapping

EXPECTATIONS_SCHEMA_NAME = "expectations.v1.schema.json"


@dataclass(frozen=True)
class Expectations:
    expect_fail: dict[str, str]  # scenario name -> why this swarm is expected to fail it
    source: str | None = None

    def apply(self, spec: ScenarioSpec) -> ScenarioSpec:
        """``spec`` with this swarm's expectation in place of the one its file declares."""
        reason = self.expect_fail.get(spec.name)
        if reason is None:
            return replace(spec, expect="pass", expect_reason=None)
        return replace(spec, expect="fail", expect_reason=reason)

    def unused(self, names: Iterable[str]) -> list[str]:
        """The scenarios named here that are not among ``names``, in the file's order."""
        known = set(names)
        return [name for name in self.expect_fail if name not in known]


def parse_expectations(document: dict, source: str | None = None) -> Expectations:
    """Validates ``document`` against the schema and builds the expectations, or raises
    ScenarioError."""
    where = source or "expectations"
    check_against_schema(document, where, EXPECTATIONS_SCHEMA_NAME)
    expect_fail = {}
    for name, reason in document.get("expect_fail", {}).items():
        if not reason.split():
            raise ScenarioError(f"{where}: expect_fail {name} needs a reason saying why")
        expect_fail[name] = " ".join(reason.split())
    return Expectations(expect_fail, source)


def load_expectations(path: str | Path) -> Expectations:
    return parse_expectations(read_mapping(path, "an expectations file"), source=str(path))
