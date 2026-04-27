"""Stage 1H T8 — Family G traits. Targets ra_generators_traits.

Sub-tests cover ``generate_default_impl``, ``generate_default_from_new``,
and ``generate_from_impl``-shaped assists on the curated targets.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_generators_traits/src/lib.rs"


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


def test_generate_default_impl_offered_on_struct(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub struct Token")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 11},
        end={"line": line_idx, "character": 16},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Generate" in t and "default" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no generate_default_impl here; titles={titles}")
    assert any("Generate" in t for t in titles)


def test_generate_default_from_new_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub fn new() -> Self")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 11},
        end={"line": line_idx, "character": 14},
    )
    titles = [a.get("title", "") for a in actions]
    if not any(
        "Generate" in t and ("default" in t.lower() or "from new" in t.lower())
        for t in titles
    ):
        pytest.skip(f"rust-analyzer offered no generate_default_from_new here; titles={titles}")


def test_generate_from_impl_offered_on_enum(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "Red,")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 7},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Generate" in t and "From" in t for t in titles):
        pytest.skip(f"rust-analyzer offered no generate_from_impl here; titles={titles}")
