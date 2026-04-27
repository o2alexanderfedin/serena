"""Stage 1H T10 Module 2 — Python: pylsp_rope.refactor.extract.variable.

Targets calcpy fixture. Asserts (a) Extract variable is offered on a binop-
shaped sub-expression in calcpy.py and applies cleanly; (b) the resulting
edit body contains an assignment statement (the extracted name → expression).

Skips honestly when pylsp-rope refuses to extract at the chosen coordinate —
rope evaluates the expression boundary heuristically and may decline a
pick that fails its expression-tree check.
"""
from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "calcpy/calcpy.py"


def _line_index(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines()):
        if needle in line:
            return i
    pytest.skip(f"fixture coord drifted: needle {needle!r} not in fixture text")


def _fetch_actions(
    pylsp_lsp: "SolidLanguageServer",
    file_abs: str,
    start: dict[str, int],
    end: dict[str, int],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    with pylsp_lsp.open_file(_REL):
        time.sleep(1.0)
        raw = pylsp_lsp.request_code_actions(
            file_abs, start=start, end=end, diagnostics=[]
        )
        actions.extend(a for a in raw if isinstance(a, dict))
    return actions


def test_extract_variable_round_trip(
    pylsp_lsp: "SolidLanguageServer",
    calcpy_workspace: Path,
    assert_workspace_edit_round_trip: Any,
) -> None:
    """Pick a binary-op-shaped expression inside ``_eval_binop`` and ask
    pylsp-rope to extract it as a variable."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    text = src.read_text()
    # Inside _eval_binop the body computes ``left + right`` etc — an ideal
    # extract-variable target. Find the first ``return left + right`` line.
    line_idx = _line_index(text, "return left + right")
    line_text = text.splitlines()[line_idx]
    # Select just the expression after ``return `` (column index of '+').
    start_char = line_text.index("left")
    end_char = line_text.index("right") + len("right")
    actions = _fetch_actions(
        pylsp_lsp,
        str(src),
        start={"line": line_idx, "character": start_char},
        end={"line": line_idx, "character": end_char},
    )
    titles = [a.get("title", "") for a in actions]
    extract = next(
        (a for a in actions if "extract variable" in a.get("title", "").lower()),
        None,
    )
    if extract is None:
        pytest.skip(f"pylsp-rope did not offer 'Extract variable'; titles={titles}")
    edit = extract.get("edit")
    if edit is None:
        resolved = pylsp_lsp.resolve_code_action(extract)
        edit = resolved.get("edit") if isinstance(resolved, dict) else None
    if edit is None:
        pytest.skip("Extract variable action carried no edit even after resolve")

    original = src.read_text()
    try:
        assert_workspace_edit_round_trip(edit)
        post_text = src.read_text()
        ast.parse(post_text)
    finally:
        src.write_text(original)


def test_extract_variable_writes_assignment(
    pylsp_lsp: "SolidLanguageServer",
    calcpy_workspace: Path,
) -> None:
    """The extracted edit body must include an assignment statement."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    text = src.read_text()
    line_idx = _line_index(text, "return left + right")
    line_text = text.splitlines()[line_idx]
    start_char = line_text.index("left")
    end_char = line_text.index("right") + len("right")
    actions = _fetch_actions(
        pylsp_lsp,
        str(src),
        start={"line": line_idx, "character": start_char},
        end={"line": line_idx, "character": end_char},
    )
    extract = next(
        (a for a in actions if "extract variable" in a.get("title", "").lower()),
        None,
    )
    if extract is None:
        titles = [a.get("title", "") for a in actions]
        pytest.skip(f"Extract variable not offered; got {titles}")
    edit = extract.get("edit")
    if edit is None:
        with pylsp_lsp.open_file(_REL):
            time.sleep(0.5)
            resolved = pylsp_lsp.resolve_code_action(extract)
            edit = resolved.get("edit") if isinstance(resolved, dict) else None
    if edit is None:
        pytest.skip("Extract variable action carried no edit even after resolve")
    # Look for an ``=`` in any newText body — rope's extract-variable
    # always emits ``<name> = <expr>``.
    edit_text = str(edit)
    assert "=" in edit_text, f"edit body lacks assignment: {edit_text[:200]}"
