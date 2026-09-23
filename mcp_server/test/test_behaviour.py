"""mcp_server/BEHAVIOUR.md is normative: every tool matches its row, and the rules hold."""

import dataclasses
import inspect
import re
from pathlib import Path

import pytest

from mcp_server.tools import TOOLS, ToolSpec

ROOT = Path(__file__).resolve().parents[2]
YES_NO = {"yes": True, "no": False}


def _table(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("| `") or (
            line.startswith("| ") and "`/" in line and "|---" not in line
        ):
            rows.append(cells)
    return rows


def _behaviour() -> dict[str, list[str]]:
    rows = _table(ROOT / "mcp_server" / "BEHAVIOUR.md")
    return {cells[0].strip("`"): cells for cells in rows}


def _api_classes() -> dict[str, str]:
    """`METHOD /path` → class, from docs/architecture/API-SURFACE.md ({id:guid} → {id})."""
    classes = {}
    for cells in _table(ROOT / "docs" / "architecture" / "API-SURFACE.md"):
        route = cells[1].strip("`").replace("{id:guid}", "{id}")
        classes[f"{cells[0]} {route}"] = cells[2]
    return classes


def check_rows(tools):
    """Every tool matches its BEHAVIOUR.md row, and every row is a tool."""
    rows = _behaviour()

    assert set(rows) == {t.name for t in tools}
    for tool in tools:
        name, classification, read_only, destructive, idempotent, open_world, calls = rows[
            tool.name
        ]
        assert classification == tool.classification, tool.name
        assert (YES_NO[read_only], YES_NO[destructive], YES_NO[idempotent], YES_NO[open_world]) == (
            tool.read_only,
            tool.destructive,
            tool.idempotent,
            tool.open_world,
        ), tool.name
        assert calls.strip("`") == tool.endpoint, tool.name


def check_endpoint_classes(tools):
    """Each tool has the class of the endpoint it calls (docs/architecture/API-SURFACE.md)."""
    api = _api_classes()

    for tool in tools:
        assert api[tool.endpoint] == tool.classification, f"{tool.name} calls {tool.endpoint}"


def check_read_only(tools):
    """Reads are read-only and nothing else is."""
    for tool in tools:
        assert tool.read_only == (tool.classification == "read"), tool.name
        assert not (tool.read_only and tool.destructive), tool.name


def check_gate(tools):
    """Rule 1: no tool approves, and the only tool that flies needs an approval code."""
    endpoints = {t.endpoint for t in tools}
    flying = [t for t in tools if t.classification in ("gated-write", "write")]

    assert not any(re.search(r"/(approve|reject)$", e) for e in endpoints)
    assert "POST /api/missions" not in endpoints  # direct dispatch, no approval
    assert [t.name for t in flying] == ["dispatch_mission"]
    assert "approval_code" in inspect.signature(flying[0].run).parameters


def check_stopping(tools):
    """Rule 2: stopping needs no approval."""
    for tool in (t for t in tools if t.classification == "safety-write"):
        assert "approval_code" not in inspect.signature(tool.run).parameters, tool.name
        assert tool.destructive, tool.name


CHECKS = (check_rows, check_endpoint_classes, check_read_only, check_gate, check_stopping)


def test_every_tool_matches_its_row_and_every_row_is_a_tool():
    check_rows(TOOLS)


def test_each_tool_has_the_class_of_the_endpoint_it_calls():
    check_endpoint_classes(TOOLS)


def test_reads_are_read_only_and_everything_else_is_not():
    check_read_only(TOOLS)


def test_no_tool_can_approve_or_fly_without_the_gate():
    check_gate(TOOLS)


def test_stopping_needs_no_approval():
    check_stopping(TOOLS)


# --- The checks can fail (architecture-standards AI-EVALS §9) ---------------------------
# Each variant breaks one thing BEHAVIOUR.md forbids. A variant is caught only by a check
# failing on an assertion — any other exception is a broken harness, not a catch, and
# fails the test.


def _approve(client, plan_id):
    return {}


def _fly_now(client, name, waypoints):
    return {}


def _dispatch_without_code(client, plan_id):
    return {}


def _abort_with_approval(client, mission_id, approval_code, action="rtl"):
    return {}


def _replace(name, **changes):
    return tuple(dataclasses.replace(t, **changes) if t.name == name else t for t in TOOLS)


BROKEN = {
    "an agent can approve its own plan": TOOLS
    + (
        ToolSpec(
            "approve_plan",
            "Approve",
            "approval",
            False,
            False,
            True,
            True,
            "POST /api/mission-plans/{id}/approve",
            _approve,
        ),
    ),
    "an agent can fly with no approval (the old start_mission)": TOOLS
    + (
        ToolSpec(
            "start_mission",
            "Start",
            "write",
            False,
            True,
            False,
            True,
            "POST /api/missions",
            _fly_now,
        ),
    ),
    "the same, disguised as a read": TOOLS
    + (
        ToolSpec(
            "start_mission",
            "Start",
            "read",
            True,
            False,
            True,
            False,
            "POST /api/missions",
            _fly_now,
        ),
    ),
    "dispatch no longer needs the code": _replace("dispatch_mission", run=_dispatch_without_code),
    "stopping waits for approval": _replace("abort_mission", run=_abort_with_approval),
    "land_all is no longer marked destructive": _replace("land_all", destructive=False),
    "a write is classified as a read": _replace(
        "land_all", classification="read", read_only=True, destructive=False
    ),
}


def _caught_by(tools) -> list[str]:
    caught = []
    for check in CHECKS:
        try:
            check(tools)
        except AssertionError:
            caught.append(check.__name__)
    return caught


def test_the_real_tools_pass_every_check():
    assert _caught_by(TOOLS) == []


@pytest.mark.parametrize("variant", BROKEN)
def test_a_broken_tool_set_is_caught(variant):
    assert _caught_by(BROKEN[variant]), f"no check caught: {variant}"
