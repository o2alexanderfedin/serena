"""v1.5 G4-10 — ignore_diagnostic honors rule (HI-11).

Acid tests:
  * When the LSP returns N quickfix actions for distinct rules, the
    facade now picks the action whose title substring matches the
    caller-named rule (via the shared dispatcher's title_match seam).
    Previously the LSP-first action was applied regardless of which
    rule it silenced.
  * When no action's title matches the caller-named rule, the facade
    returns an INPUT_NOT_HONORED-shaped envelope (status='skipped',
    reason='no_candidate_matched_title_match') and the file is left
    untouched.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import IgnoreDiagnosticTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def python_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "main.py"
    src.write_text("import os\nx = 1\n", encoding="utf-8")
    return tmp_path


def _make_tool(project_root: Path) -> Any:
    tool = IgnoreDiagnosticTool.__new__(IgnoreDiagnosticTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str, kind: str):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.kind = kind
    a.is_preferred = False
    a.provenance = "ruff"
    return a


def test_ignore_diagnostic_picks_rule_specific_action(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**_kw):
        # Order matters: E501 first so the pre-G1 LSP-first selection
        # would have applied the wrong rule. Honoring `rule="F401"`
        # requires title_match to skip past E501 and pick F401.
        return [
            _action("ruff:E501", "Disable E501: line-too-long",
                    "quickfix.ruff_noqa"),
            _action("ruff:F401", "Disable F401: unused-import",
                    "quickfix.ruff_noqa"),
        ]

    fake_coord.merge_code_actions = _actions

    def _resolve(aid):
        # Both ids resolve to a rule-specific noqa edit; the dispatcher
        # must select F401 *because of title_match*, not by chance of
        # which one happened to resolve first.
        if aid == "ruff:F401":
            return {"changes": {src.as_uri(): [{
                "range": {"start": {"line": 0, "character": 9},
                          "end": {"line": 0, "character": 9}},
                "newText": "  # noqa: F401",
            }]}}
        if aid == "ruff:E501":
            return {"changes": {src.as_uri(): [{
                "range": {"start": {"line": 0, "character": 9},
                          "end": {"line": 0, "character": 9}},
                "newText": "  # noqa: E501",
            }]}}
        return None

    fake_coord.get_action_edit = _resolve

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            tool_name="ruff",
            rule="F401",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    body = src.read_text(encoding="utf-8")
    assert "# noqa: F401" in body, body
    # Silenced rule did not leak into the file:
    assert "E501" not in body, body


def test_ignore_diagnostic_input_not_honored_when_rule_missing(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    pre = src.read_text(encoding="utf-8")
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**_kw):
        return [_action("ruff:E501", "Disable E501: line-too-long",
                        "quickfix.ruff_noqa")]

    fake_coord.merge_code_actions = _actions

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            tool_name="ruff",
            rule="F401",
            language="python",
        )
    payload = json.loads(out)
    # Honest envelope: caller's rule was not honored by any candidate.
    assert payload.get("status") == "skipped", payload
    assert payload.get("reason") == "no_candidate_matched_title_match", payload
    # File untouched:
    assert src.read_text(encoding="utf-8") == pre


def test_ignore_diagnostic_pyright_path_threads_rule(python_workspace):
    """tool_name='pyright' takes the same title_match path."""
    tool = _make_tool(python_workspace)
    src = python_workspace / "main.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        return [
            _action("bp:1", "Pyright: ignore reportMissingImports",
                    "quickfix.pyright_ignore"),
            _action("bp:2", "Pyright: ignore reportUnusedVariable",
                    "quickfix.pyright_ignore"),
        ]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: (
        {"changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 9},
                      "end": {"line": 0, "character": 9}},
            "newText": "  # pyright: ignore[reportMissingImports]",
        }]}} if aid == "bp:1" else None
    )

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            tool_name="pyright",
            rule="reportMissingImports",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    body = src.read_text(encoding="utf-8")
    assert "reportMissingImports" in body, body
    assert "reportUnusedVariable" not in body, body
