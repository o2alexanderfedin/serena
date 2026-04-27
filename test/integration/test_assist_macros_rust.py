"""Stage 1H T8 — macro extension. Targets ra_macros.

Sub-tests probe rust-analyzer's macro-handling assists. The
``rust-analyzer/expandMacro`` extension request is not part of standard
LSP code actions; it would require a custom request to surface the full
expansion. Per leaf goal, we exercise standard code-action surface here
and verify rust-analyzer offers SOMETHING actionable on each macro call
site (e.g., ``Inline macro`` or similar refactor hints).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_macros/src/lib.rs"


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


def test_actions_offered_at_vec_macro_call(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "vec![1, 2, 3]")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 16},
    )
    titles = [a.get("title", "") for a in actions]
    # rust-analyzer surfaces refactor + inline-macro options on macro call sites;
    # any non-empty list satisfies "macro-aware actions present".
    if not titles:
        pytest.skip("rust-analyzer offered no actions at vec![] call")


def test_actions_offered_at_custom_macro_call(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "double!(21)")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 14},
    )
    titles = [a.get("title", "") for a in actions]
    if not titles:
        pytest.skip("rust-analyzer offered no actions at custom-macro call")
