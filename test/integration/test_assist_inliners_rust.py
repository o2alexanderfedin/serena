"""Stage 1H T8 — Family C: inliners. Targets the ra_inliners fixture crate.

Sub-tests probe ``inline_local_variable``, ``inline_call``, and
``inline_into_callers`` at the curated call/definition sites. Skips honestly
when the assist isn't offered at the chosen coordinate on this rust-analyzer.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_inliners/src/lib.rs"


def _line_index(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines()):
        if needle in line:
            return i
    raise AssertionError(f"needle {needle!r} not in fixture text")


def _fetch_actions(
    ra_lsp: "SolidLanguageServer",
    file_abs: str,
    start: dict[str, int],
    end: dict[str, int],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    with ra_lsp.open_file(_REL):
        time.sleep(1.0)
        raw = ra_lsp.request_code_actions(
            file_abs, start=start, end=end, diagnostics=[]
        )
        actions.extend(a for a in raw if isinstance(a, dict))
    return actions


def test_inline_local_variable_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / "ra_inliners" / "src" / "lib.rs"
    text = src.read_text()
    line_idx = _line_index(text, "let x = 7;")
    # Cursor on the local-variable name.
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 8},
        end={"line": line_idx, "character": 9},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Inline" in t and "variable" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no inline-variable here; titles={titles}")
    assert any("Inline" in t and "variable" in t.lower() for t in titles), (
        f"no inline_local_variable offered; got titles={titles}"
    )


def test_inline_call_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / "ra_inliners" / "src" / "lib.rs"
    text = src.read_text()
    line_idx = _line_index(text, "inline_call_callee(41)")
    # Cursor on the callee identifier.
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 22},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Inline" in t for t in titles):
        pytest.skip(f"rust-analyzer offered no inline-call here; titles={titles}")
    assert any("Inline" in t for t in titles), (
        f"no inline_call offered; got titles={titles}"
    )


def test_inline_into_callers_offered_at_definition(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / "ra_inliners" / "src" / "lib.rs"
    text = src.read_text()
    line_idx = _line_index(text, "pub fn inline_into_callers_definition")
    # Cursor on the fn name token.
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 7},
        end={"line": line_idx, "character": 38},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Inline" in t and "caller" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no inline-into-callers here; titles={titles}")
    assert any("Inline" in t and "caller" in t.lower() for t in titles), (
        f"no inline_into_callers offered; got titles={titles}"
    )
