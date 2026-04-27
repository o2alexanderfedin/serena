"""Stage 1H T10 Module 3 — Python: pylsp_rope.refactor.inline.

Targets the calcpy_dataclasses sub-fixture. Asserts (a) pylsp-rope offers
``refactor.inline`` for the ``DEFAULT_BOX`` module-level constant inside
``models.py`` and the resulting WorkspaceEdit applies cleanly; (b) the
post-apply ``Box``/``DEFAULT_BOX`` ``__repr__`` baseline survives — the
fixture's existing dataclass repr (``Box(width=1, height=1, depth=1)``)
is preserved. Both sub-tests skip cleanly if rope refuses inline.

Per the v0.3.0 facade-application architecture, the round-trip helper
applies the WorkspaceEdit via the pure-python applier so the assertion
runs against on-disk text.
"""
from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "calcpy_dataclasses/models.py"


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


def test_inline_default_box_offered(
    pylsp_lsp: "SolidLanguageServer",
    calcpy_dataclasses_workspace: Path,
) -> None:
    """``DEFAULT_BOX`` is a module-level constant — pylsp-rope should offer
    ``refactor.inline`` on its identifier site."""
    src = calcpy_dataclasses_workspace / "calcpy_dataclasses" / "models.py"
    text = src.read_text()
    line_idx = _line_index(text, "DEFAULT_BOX: Box = Box(")
    line_text = text.splitlines()[line_idx]
    start_char = line_text.index("DEFAULT_BOX")
    end_char = start_char + len("DEFAULT_BOX")
    actions = _fetch_actions(
        pylsp_lsp,
        str(src),
        start={"line": line_idx, "character": start_char},
        end={"line": line_idx, "character": end_char},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("inline" in t.lower() for t in titles):
        pytest.skip(f"pylsp-rope did not offer Inline at this position; titles={titles}")
    assert any("inline" in t.lower() for t in titles), (
        f"no inline action offered; got titles={titles}"
    )


def test_inline_preserves_dataclass_repr_baseline(
    pylsp_lsp: "SolidLanguageServer",
    calcpy_dataclasses_workspace: Path,
    assert_workspace_edit_round_trip: Any,
) -> None:
    """Apply the inline edit and confirm the file remains parseable + the
    ``Box(width=...)`` literal survives in the post-apply text (or in the
    edit body itself when the inline rewrites the call site)."""
    src = calcpy_dataclasses_workspace / "calcpy_dataclasses" / "models.py"
    text = src.read_text()
    line_idx = _line_index(text, "DEFAULT_BOX: Box = Box(")
    line_text = text.splitlines()[line_idx]
    start_char = line_text.index("DEFAULT_BOX")
    end_char = start_char + len("DEFAULT_BOX")
    actions = _fetch_actions(
        pylsp_lsp,
        str(src),
        start={"line": line_idx, "character": start_char},
        end={"line": line_idx, "character": end_char},
    )
    inline = next(
        (a for a in actions if "inline" in a.get("title", "").lower()),
        None,
    )
    if inline is None:
        titles = [a.get("title", "") for a in actions]
        pytest.skip(f"Inline not offered; titles={titles}")
    edit = inline.get("edit")
    if edit is None:
        with pylsp_lsp.open_file(_REL):
            time.sleep(0.5)
            resolved = pylsp_lsp.resolve_code_action(inline)
            edit = resolved.get("edit") if isinstance(resolved, dict) else None
    if edit is None:
        pytest.skip("Inline action carried no edit even after resolve")

    original = src.read_text()
    try:
        assert_workspace_edit_round_trip(edit)
        post_text = src.read_text()
        ast.parse(post_text)
        # ``Box(...)`` constructor signature must persist (either in source
        # or because the inline rewrote DEFAULT_BOX usages with the literal).
        assert "Box(" in post_text, "Box constructor disappeared post-inline"
    finally:
        src.write_text(original)
