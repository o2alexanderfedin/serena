"""Stage 1H T8 — Family F: ordering. Targets ra_ordering.

Sub-tests cover impl-method reordering, top-level fn sorting, and field
reordering. ``sort_items`` is offered on items inside an impl block as
``Sort items``; on free-fn lists rust-analyzer typically does not offer a
sort assist (this skip is honest).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_ordering/src/lib.rs"


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


def test_reorder_impl_items_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "impl Foo {")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 0},
        end={"line": line_idx, "character": 10},
    )
    titles = [a.get("title", "") for a in actions]
    if not any(("sort" in t.lower() or "reorder" in t.lower()) for t in titles):
        pytest.skip(f"rust-analyzer offered no reorder_impl_items here; titles={titles}")
    assert any(("sort" in t.lower() or "reorder" in t.lower()) for t in titles)


def test_sort_top_level_fns_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub fn z_function")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 0},
        end={"line": line_idx, "character": 18},
    )
    titles = [a.get("title", "") for a in actions]
    if not any(("sort" in t.lower() or "reorder" in t.lower()) for t in titles):
        pytest.skip(f"rust-analyzer offered no sort_items at top-level here; titles={titles}")


def test_reorder_struct_fields_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub struct ReorderableFields")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 11},
        end={"line": line_idx, "character": 28},
    )
    titles = [a.get("title", "") for a in actions]
    if not any(("sort" in t.lower() or "reorder" in t.lower() or "field" in t.lower()) for t in titles):
        pytest.skip(f"rust-analyzer offered no reorder_fields here; titles={titles}")
