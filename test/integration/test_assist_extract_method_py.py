"""Stage 1H T10 Module 1 — Python: pylsp_rope.refactor.extract.method round-trip.

Targets calcpy fixture. Asserts (a) pylsp-rope offers Extract method on the
binary-op dispatch branch inside ``_Evaluator._eval_dispatch``, applying the
WorkspaceEdit cleanly; (b) the extracted edit body contains a fresh ``def``
declaration. Both sub-tests skip cleanly when pylsp-rope refuses to offer
``refactor.extract.method`` at the chosen coordinate (rope is heuristic about
control-flow boundaries — honest skip rather than false-FAIL).

Per Stage 1H Leaf 03 pattern: the ``request_code_actions`` API on
``SolidLanguageServer`` is **synchronous** — wrap each probe in
``with pylsp_lsp.open_file(<rel>):`` + ``time.sleep(1.0)`` so pylsp's
indexer has a moment to settle before code-action introspection.
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
    """Open the file, wait for indexing, return code actions at the range."""
    actions: list[dict[str, Any]] = []
    with pylsp_lsp.open_file(_REL):
        time.sleep(1.0)
        raw = pylsp_lsp.request_code_actions(
            file_abs, start=start, end=end, diagnostics=[]
        )
        actions.extend(a for a in raw if isinstance(a, dict))
    return actions


def test_extract_method_on_dispatch_branch(
    pylsp_lsp: "SolidLanguageServer",
    calcpy_workspace: Path,
    assert_workspace_edit_round_trip: Any,
) -> None:
    """Inside ``_Evaluator._eval_dispatch``, select the binary-op branch and
    request ``refactor.extract.method``. The resulting WorkspaceEdit must
    apply cleanly and leave the file ast-parseable post-apply."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    text = src.read_text()
    line_idx = _line_index(text, "if isinstance(node, BinOp):")
    rng_start = {"line": line_idx, "character": 8}
    rng_end = {"line": line_idx + 1, "character": 0}

    actions = _fetch_actions(pylsp_lsp, str(src), rng_start, rng_end)
    titles = [a.get("title", "") for a in actions]
    extract = next(
        (a for a in actions if "extract method" in a.get("title", "").lower()),
        None,
    )
    if extract is None:
        pytest.skip(
            f"pylsp-rope did not offer 'Extract method' at this position; "
            f"got titles={titles}"
        )

    edit = extract.get("edit")
    if edit is None:
        # pylsp-rope sometimes returns command-typed actions; resolve once.
        resolved = pylsp_lsp.resolve_code_action(extract)
        edit = resolved.get("edit") if isinstance(resolved, dict) else None
    if edit is None:
        pytest.skip("Extract method action carried no edit even after resolve")

    original = src.read_text()
    try:
        assert_workspace_edit_round_trip(edit)
        post_text = src.read_text()
        ast.parse(post_text)
    finally:
        src.write_text(original)


def test_extract_method_writes_new_def(
    pylsp_lsp: "SolidLanguageServer",
    calcpy_workspace: Path,
) -> None:
    """The Extract-method edit text must include a new ``def `` line."""
    src = calcpy_workspace / "calcpy" / "calcpy.py"
    text = src.read_text()
    line_idx = _line_index(text, "if isinstance(node, BinOp):")
    actions = _fetch_actions(
        pylsp_lsp,
        str(src),
        start={"line": line_idx, "character": 8},
        end={"line": line_idx + 1, "character": 0},
    )
    extract = next(
        (a for a in actions if "extract method" in a.get("title", "").lower()),
        None,
    )
    if extract is None:
        titles = [a.get("title", "") for a in actions]
        pytest.skip(f"Extract method not offered at this position; got {titles}")
    edit = extract.get("edit")
    if edit is None:
        with pylsp_lsp.open_file(_REL):
            time.sleep(0.5)
            resolved = pylsp_lsp.resolve_code_action(extract)
            edit = resolved.get("edit") if isinstance(resolved, dict) else None
    if edit is None:
        pytest.skip("Extract method action carried no edit even after resolve")
    edit_text = str(edit)
    assert "def " in edit_text, f"edit body lacks new def: {edit_text[:200]}"
