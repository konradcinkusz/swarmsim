"""Command line: python -m swarm_coordination.scenarios {run,validate,mutants} ...

    run       [PATH ...] [--seed N] [--seeds K] [--sut MODULE:ATTR] [--mutants]
              [--junit FILE] [--json FILE] [--markdown FILE] [--traces DIR]
              [--upload API_URL [--label TEXT]]   (token: $SWARMSIM_API_TOKEN)
    validate  [PATH ...]       check scenario files against the schema, run nothing
    mutants                    list the broken swarms the mutation check uses

PATH is a scenario file or a directory searched for *.yaml (default: ./scenarios).
Exit status: 0 when every scenario met its expectation (and, with --mutants, every
scenario failed at least one mutant and every mutant was failed by one), 1 when not,
2 when the scenarios or the arguments could not be used. A failed --upload is reported
and never changes it: the verdict is made here, storing it is only remembering it.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

from .mutants import MUTANTS
from .runner import run_suite, to_json, to_junit, to_markdown
from .spec import ScenarioError, discover, load_scenario
from .sut import ReferenceSwarm
from .upload import TOKEN_VARIABLE, UploadError, upload_report


def _load_sut(reference: str | None):
    if not reference:
        return ReferenceSwarm()
    module_name, _, attribute = reference.partition(":")
    if not module_name or not attribute:
        raise ScenarioError(f"--sut must be MODULE:ATTRIBUTE, got '{reference}'")
    sys.path.insert(0, str(Path.cwd()))
    try:
        target = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise ScenarioError(f"--sut {reference}: {exc}") from None
    # A class or a factory function is called; an object that already is a swarm is used.
    is_swarm = not isinstance(target, type) and hasattr(target, "ground")
    sut = target if is_swarm else target()
    for needed in ("name", "ground", "drone"):
        if not hasattr(sut, needed):
            raise ScenarioError(f"--sut {reference}: has no '{needed}' (see scenarios/sut.py)")
    return sut


def _write(path: str | None, text: str) -> None:
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m swarm_coordination.scenarios")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run scenarios against a system under test")
    run.add_argument("paths", nargs="*", default=["scenarios"])
    run.add_argument("--seed", type=int, default=1, help="first seed (default 1)")
    run.add_argument("--seeds", type=int, default=1, help="how many seeds per scenario")
    run.add_argument("--sut", help="MODULE:ATTRIBUTE of another swarm (default: this repo's)")
    run.add_argument("--mutants", action="store_true", help="also run the mutation check")
    run.add_argument("--junit", help="write a JUnit XML report here")
    run.add_argument("--json", help="write a JSON report here")
    run.add_argument("--markdown", help="write a Markdown summary here (appends)")
    run.add_argument("--traces", help="write the trace of every failing run into this directory")
    run.add_argument(
        "--upload", metavar="API_URL", help="also store the report in SwarmApi.Api at this URL"
    )
    run.add_argument("--label", help="what was tested, for --upload (default: the commit, in CI)")

    validate = commands.add_parser("validate", help="check scenario files, run nothing")
    validate.add_argument("paths", nargs="*", default=["scenarios"])

    commands.add_parser("mutants", help="list the mutants the mutation check uses")

    args = parser.parse_args(argv)

    if args.command == "mutants":
        for mutant in MUTANTS:
            print(f"{mutant.name:28} {mutant.breaks}")
        return 0

    if args.command == "validate":
        try:
            files = discover(args.paths)
            for path in files:
                spec = load_scenario(path)
                print(
                    f"ok  {path}  ({spec.name}: {len(spec.events)} events, "
                    f"{len(spec.assertions)} assertions)"
                )
        except ScenarioError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0 if files else 2

    if args.seeds < 1:
        parser.error("--seeds must be at least 1")
    try:
        sut = _load_sut(args.sut)
    except ScenarioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.mutants and args.sut:
        print(
            "error: --mutants breaks this repo's swarm on purpose; it cannot mutate --sut",
            file=sys.stderr,
        )
        return 2

    seeds = list(range(args.seed, args.seed + args.seeds))
    report = run_suite(
        args.paths,
        sut,
        seeds,
        mutation=args.mutants,
        trace_dir=Path(args.traces) if args.traces else None,
    )
    markdown = to_markdown(report)
    print(markdown)
    _write(args.junit, to_junit(report))
    _write(args.json, json.dumps(to_json(report), indent=2))
    if args.markdown:
        with open(args.markdown, "a", encoding="utf-8") as summary:
            summary.write(markdown)
    if args.upload:
        _upload(args.upload, to_json(report), args.label or _default_label())
    if report.errors and not report.scenarios:
        return 2
    return 0 if report.ok else 1


def _default_label() -> str | None:
    """In GitHub Actions, the commit and branch; elsewhere nothing."""
    sha = os.environ.get("GITHUB_SHA", "")[:12]
    ref = os.environ.get("GITHUB_REF_NAME", "")
    return " ".join(part for part in (sha, ref) if part) or None


def _upload(api: str, report: dict, label: str | None) -> None:
    try:
        stored = upload_report(api, report, label, os.environ.get(TOKEN_VARIABLE) or None)
    except UploadError as exc:
        prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") == "true" else "warning: "
        print(f"{prefix}the report was not stored: {exc}", file=sys.stderr)
        return
    print(f"stored as scenario run {stored.get('id')} at {api.rstrip('/')}/api/scenario-runs")


if __name__ == "__main__":
    sys.exit(main())
