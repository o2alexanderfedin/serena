"""v1.5 G4-8 — fix_lints honors `rules` allow-list (HI-9).

Acid tests:
  * rules=["I001"] dispatches ONE call carrying
    ``arguments=[{"select": ["I001"]}]``; real-disk read confirms only
    the I001 fix landed.
  * rules=["I001", "F401"] dispatches TWO calls (one per rule); edits
    merged via _merge_workspace_edits.
  * rules=None preserves today's full-auto-fix behavior — one dispatch
    with no `select` argument.
  * The end-of-range no longer hardcodes (0,0); it uses
    compute_file_range so the LSP request brackets the whole file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ScalpelFixLintsTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def python_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "main.py"
    src.write_text(
        "import os\n"
        "import os  # I001 dup\n"
        "x = 1  # E501 line-length placeholder\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_tool(project_root: Path) -> Any:
    tool = ScalpelFixLintsTool.__new__(ScalpelFixLintsTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.kind = "source.fixAll.ruff"
    a.is_preferred = False
    a.provenance = "ruff"
    return a


def test_fix_lints_with_single_rule_dispatches_per_rule(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        rule_arg = (kw.get("arguments") or [{}])[0].get("select", [None])[0]
        return [_action(f"ruff:{rule_arg}", f"Fix {rule_arg}")]

    fake_coord.merge_code_actions = _actions

    def _resolve(aid):
        if "I001" in aid:
            return {"changes": {src.as_uri(): [{
                "range": {"start": {"line": 1, "character": 0},
                          "end": {"line": 2, "character": 0}},
                "newText": "",
            }]}}
        return None

    fake_coord.get_action_edit = _resolve

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            rules=["I001"],
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload

    # Per-rule dispatch: exactly ONE call, with I001 in arguments.select:
    assert len(captured) == 1, captured
    args0 = captured[0].get("arguments") or [{}]
    select = args0[0].get("select") if args0 else None
    assert select == ["I001"], captured

    # Real-disk acid test: I001 dup line removed:
    body = src.read_text(encoding="utf-8")
    assert body.count("import os") == 1


def test_fix_lints_with_multiple_rules_dispatches_per_rule_and_merges(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        rule_arg = (kw.get("arguments") or [{}])[0].get("select", [None])[0]
        return [_action(f"ruff:{rule_arg}", f"Fix {rule_arg}")]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {src.as_uri(): [{
        "range": {"start": {"line": 0, "character": 0},
                  "end": {"line": 0, "character": 0}},
        "newText": "",
    }]}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            rules=["I001", "F401"],
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert len(captured) == 2, captured
    # Each call carries exactly one rule:
    selects: list[str] = []
    for c in captured:
        args = c.get("arguments") or [{}]
        sel = (args[0].get("select") if args else None) or []
        if sel and isinstance(sel[0], str):
            selects.append(sel[0])
    assert sorted(selects) == ["F401", "I001"]


def test_fix_lints_no_rules_means_all(python_workspace):
    """rules=None preserves today's behavior — one dispatch with no
    `select` filter."""
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        return [_action("ruff:1", "Fix all")]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {src.as_uri(): [{
        "range": {"start": {"line": 0, "character": 0},
                  "end": {"line": 0, "character": 0}},
        "newText": "",
    }]}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            rules=None,
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert len(captured) == 1
    args0 = captured[0].get("arguments")
    # No select filter → arguments either absent or no `select` key:
    assert not args0 or not (args0[0] or {}).get("select")


def test_fix_lints_uses_real_file_range_not_zero_zero(python_workspace):
    """The LSP request brackets the whole file via compute_file_range,
    not a degenerate (0,0)→(0,0) range."""
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        return [_action("ruff:1", "Fix all")]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        tool.apply(
            file=str(src),
            language="python",
        )
    assert captured
    # End is no longer (0,0); compute_file_range returns end-of-file.
    end = captured[0].get("end") or {}
    assert (end.get("line"), end.get("character")) != (0, 0), captured
