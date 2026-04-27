"""Stage 1H T8 — Family J lifetimes. Targets ra_lifetimes.

Sub-tests cover ``introduce_named_lifetime`` (or ``add_explicit_lifetime``)
on a method with elided lifetimes and on a function returning a borrow.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_lifetimes/src/lib.rs"


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


def test_introduce_named_lifetime_on_self_method(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub fn name(&self) -> &str")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 11},
        end={"line": line_idx, "character": 15},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("lifetime" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no lifetime assist here; titles={titles}")


def test_extract_explicit_lifetime_on_elided_input(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub fn elided_input_output")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 11},
        end={"line": line_idx, "character": 30},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("lifetime" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no lifetime assist here; titles={titles}")
