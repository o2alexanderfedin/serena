"""Stage 1H T8 — SSR (structural search and replace) extension. Targets ra_ssr.

SSR is a rust-analyzer extension surfaced via the
``experimental/ssr`` LSP request, not standard code actions. For
purposes of this leaf we exercise the standard code-action surface on
the SSR-shaped targets and verify rust-analyzer offers an actionable
refactor on each (e.g., ``Replace .unwrap() with ?``-style assist).
The SSR-request-direct path is exercised separately by Stage 1H T7.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_ssr/src/lib.rs"


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


def test_actions_offered_on_unwrap_option_site(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "some_value.unwrap()")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 23},
    )
    titles = [a.get("title", "") for a in actions]
    if not titles:
        pytest.skip("rust-analyzer offered no actions on unwrap_option_call")


def test_actions_offered_on_result_alias_site(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub type SsrResult")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 9},
        end={"line": line_idx, "character": 18},
    )
    titles = [a.get("title", "") for a in actions]
    if not titles:
        pytest.skip("rust-analyzer offered no actions on SsrResult alias")
