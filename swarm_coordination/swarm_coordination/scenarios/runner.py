"""A scenario suite: every scenario × every seed against one system under test, plus the
optional mutation check, and the reports CI reads (JSON, JUnit XML, Markdown).

Outcomes per scenario: ``passed`` (every seed passed), ``failed``, ``xfail`` (declared
``expect: fail`` and it did — a known limitation, written down) and ``xpass`` (declared a
failure but passed: the limitation is gone or the scenario is wrong, so it fails the
suite until someone updates it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .harness import run_scenario
from .model import Verdict
from .mutants import MUTANTS, Mutant
from .spec import ScenarioError, ScenarioSpec, discover, load_scenario
from .sut import SystemUnderTest


@dataclass
class ScenarioReport:
    spec: ScenarioSpec
    verdicts: list[Verdict]
    killed_by: list[str] | None = None  # mutants this scenario failed; None: not checked

    @property
    def all_passed(self) -> bool:
        return all(v.passed for v in self.verdicts)

    @property
    def outcome(self) -> str:
        if self.spec.expect == "fail":
            return "xpass" if self.all_passed else "xfail"
        return "passed" if self.all_passed else "failed"

    @property
    def toothless(self) -> bool:
        return self.killed_by is not None and not self.killed_by and self.spec.expect == "pass"


@dataclass
class SuiteReport:
    sut: str
    seeds: list[int]
    scenarios: list[ScenarioReport] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mutants: list[Mutant] | None = None

    def survivors(self) -> list[str]:
        if self.mutants is None:
            return []
        killed = {m for s in self.scenarios for m in (s.killed_by or [])}
        return [m.name for m in self.mutants if m.name not in killed]

    @property
    def ok(self) -> bool:
        return (
            not self.errors
            and all(s.outcome in ("passed", "xfail") for s in self.scenarios)
            and not any(s.toothless for s in self.scenarios)
            and not self.survivors()
        )

    def counts(self) -> dict[str, int]:
        counts = {"passed": 0, "failed": 0, "xfail": 0, "xpass": 0}
        for s in self.scenarios:
            counts[s.outcome] += 1
        return counts


def run_suite(
    paths: list[str | Path],
    sut: SystemUnderTest,
    seeds: list[int],
    mutation: bool = False,
    trace_dir: Path | None = None,
) -> SuiteReport:
    report = SuiteReport(sut=sut.name, seeds=list(seeds))
    try:
        files = discover(paths)
    except ScenarioError as exc:
        report.errors.append(str(exc))
        return report
    if not files:
        report.errors.append(f"no scenario files found in {', '.join(map(str, paths))}")

    specs = []
    for path in files:
        try:
            specs.append(load_scenario(path))
        except ScenarioError as exc:
            report.errors.append(str(exc))
    names = [s.name for s in specs]
    report.errors += [
        f"scenario name '{n}' is used twice" for n in sorted(set(names)) if names.count(n) > 1
    ]

    for spec in specs:
        verdicts = []
        for seed in seeds:
            verdict, trace = run_scenario(spec, sut, seed)
            verdicts.append(verdict)
            if trace_dir is not None and (not verdict.passed or spec.expect == "fail"):
                trace_dir.mkdir(parents=True, exist_ok=True)
                target = trace_dir / f"{spec.name}.seed{seed}.{sut.name.replace(':', '_')}.json"
                target.write_text(json.dumps(trace.as_dict()), encoding="utf-8")
        report.scenarios.append(ScenarioReport(spec, verdicts))

    if mutation:
        report.mutants = list(MUTANTS)
        for scenario in report.scenarios:
            # Only a scenario the real swarm passes says anything by failing a mutant.
            if scenario.outcome != "passed":
                continue
            scenario.killed_by = [
                m.name
                for m in MUTANTS
                if not run_scenario(scenario.spec, m.sut, seeds[0])[0].passed
            ]
    return report


# --- reports ------------------------------------------------------------------------------


def _verdict_dict(verdict: Verdict) -> dict:
    return {
        "seed": verdict.seed,
        "passed": verdict.passed,
        "wall_time_s": round(verdict.wall_time_s, 4),
        "assertions": [
            {
                "assertion": o.assertion,
                "passed": o.passed,
                "measured": o.measured,
                "unit": o.unit,
                "violations": [
                    {
                        "drones": list(v.drone_ids),
                        "t_s": v.timestamp_s,
                        "measured": v.measured_value,
                        "threshold": v.threshold,
                        "description": v.description,
                    }
                    for v in o.violations
                ],
            }
            for o in verdict.outcomes
        ],
    }


REPORT_VERSION = 1  # contracts/scenario/report.v1.schema.json


def to_json(report: SuiteReport) -> dict:
    return {
        "version": REPORT_VERSION,
        "sut": report.sut,
        "seeds": report.seeds,
        "ok": report.ok,
        "counts": report.counts(),
        "errors": report.errors,
        "scenarios": [
            {
                "name": s.spec.name,
                "source": s.spec.source,
                "description": s.spec.description,
                "expect": s.spec.expect,
                "expect_reason": s.spec.expect_reason,
                "outcome": s.outcome,
                "killed_mutants": s.killed_by,
                "runs": [_verdict_dict(v) for v in s.verdicts],
            }
            for s in report.scenarios
        ],
        "mutation": None
        if report.mutants is None
        else {
            "mutants": [{"name": m.name, "breaks": m.breaks} for m in report.mutants],
            "survivors": report.survivors(),
            "toothless_scenarios": [s.spec.name for s in report.scenarios if s.toothless],
        },
    }


def _failure_text(verdict: Verdict) -> str:
    return "\n".join(f"[{v.assertion}] {v.description}" for v in verdict.violations)


def to_junit(report: SuiteReport) -> str:
    suite = ElementTree.Element("testsuite", name=f"swarmsim scenarios ({report.sut})")
    tests = failures = errors = 0
    total_time = 0.0
    for error in report.errors:
        tests += 1
        errors += 1
        case = ElementTree.SubElement(suite, "testcase", classname="scenarios", name="load")
        ElementTree.SubElement(case, "error", message=error).text = error
    for scenario in report.scenarios:
        for verdict in scenario.verdicts:
            tests += 1
            total_time += verdict.wall_time_s
            case = ElementTree.SubElement(
                suite,
                "testcase",
                classname=f"scenarios.{scenario.spec.name}",
                name=f"seed {verdict.seed}",
                time=f"{verdict.wall_time_s:.4f}",
            )
            if scenario.spec.expect == "fail":
                if verdict.passed:
                    failures += 1
                    message = "passed, but the scenario declares expect: fail"
                    ElementTree.SubElement(
                        case, "failure", message=message
                    ).text = f"{message} ({scenario.spec.expect_reason})"
                else:
                    skipped = ElementTree.SubElement(
                        case, "skipped", message=f"expected failure: {scenario.spec.expect_reason}"
                    )
                    skipped.text = _failure_text(verdict)
            elif not verdict.passed:
                failures += 1
                first = verdict.violations[0].description if verdict.violations else "failed"
                ElementTree.SubElement(case, "failure", message=first).text = _failure_text(verdict)
        if scenario.killed_by is not None:
            tests += 1
            case = ElementTree.SubElement(
                suite,
                "testcase",
                classname=f"scenarios.{scenario.spec.name}",
                name="fails at least one mutant",
            )
            if scenario.toothless:
                failures += 1
                message = "no mutant fails this scenario: it would not notice a regression"
                ElementTree.SubElement(case, "failure", message=message).text = message
    for survivor in report.survivors():
        tests += 1
        failures += 1
        case = ElementTree.SubElement(
            suite, "testcase", classname="mutants", name=f"{survivor} is caught"
        )
        message = f"mutant {survivor} passes every scenario: the suite does not guard it"
        ElementTree.SubElement(case, "failure", message=message).text = message
    suite.set("tests", str(tests))
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
    suite.set("time", f"{total_time:.4f}")
    ElementTree.indent(suite)
    return ElementTree.tostring(suite, encoding="unicode", xml_declaration=True) + "\n"


_ICONS = {"passed": "✅", "failed": "❌", "xfail": "⚠️", "xpass": "❗"}


def _headline(scenario: ScenarioReport) -> str:
    parts = []
    for outcome in scenario.verdicts[0].outcomes:
        if outcome.measured is None:
            continue
        values = [
            o.measured
            for v in scenario.verdicts
            for o in v.outcomes
            if o.assertion == outcome.assertion and o.measured is not None
        ]
        low, high = min(values), max(values)
        span = f"{low:g}" if low == high else f"{low:g}–{high:g}"
        parts.append(f"{outcome.assertion} {span} {outcome.unit}")
    return "; ".join(dict.fromkeys(parts))


def to_markdown(report: SuiteReport) -> str:
    counts = report.counts()
    lines = [
        f"## Swarm scenarios — {'passed' if report.ok else 'failed'}",
        "",
        f"System under test **{report.sut}**, seeds {', '.join(map(str, report.seeds))}: "
        + ", ".join(f"{n} {k}" for k, n in counts.items() if n),
        "",
    ]
    if report.errors:
        lines += ["**Errors**", ""] + [f"- {e}" for e in report.errors] + [""]
    mutation = report.mutants is not None
    header = "| Scenario | Outcome | Measured (all seeds) |" + (
        " Mutants failed |" if mutation else ""
    )
    lines += [header, "|---|---|---|" + ("---|" if mutation else "")]
    for s in report.scenarios:
        row = f"| `{s.spec.name}` | {_ICONS[s.outcome]} {s.outcome} | {_headline(s)} |"
        if mutation:
            killed = "—" if s.killed_by is None else (", ".join(s.killed_by) or "**none**")
            row += f" {killed} |"
        lines.append(row)
    failing = [
        (s, v)
        for s in report.scenarios
        for v in s.verdicts
        if not v.passed and s.spec.expect == "pass"
    ]
    if failing:
        lines += ["", "**Violations**", ""]
        for s, v in failing:
            for violation in v.violations:
                lines.append(f"- `{s.spec.name}` seed {v.seed}: {violation.description}")
    expected = [s for s in report.scenarios if s.spec.expect == "fail"]
    if expected:
        lines += ["", "**Known limitations (expect: fail)**", ""]
        lines += [f"- `{s.spec.name}` ({s.outcome}): {s.spec.expect_reason}" for s in expected]
    if mutation:
        survivors = report.survivors()
        lines += [
            "",
            f"Mutation check: {len(report.mutants) - len(survivors)} of {len(report.mutants)} "
            "mutants caught"
            + (f"; **not caught: {', '.join(survivors)}**" if survivors else "")
            + ".",
        ]
    return "\n".join(lines) + "\n"
