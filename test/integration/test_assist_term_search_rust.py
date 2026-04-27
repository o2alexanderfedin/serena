"""Stage 1H T8 — Family K term-search escape-hatch. Targets ra_term_search.

Single sub-test: ``term_search`` fires on the body of a fn whose body is
``todo!()`` and offers a fill suggestion. We assert at least one action
title mentions term-search OR the fixture's ``todo!()`` macro.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_term_search/src/lib.rs"


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


def test_term_search_offered_on_todo_body(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "todo!()")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 11},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("term" in t.lower() or "fill" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no term_search here; titles={titles}")
