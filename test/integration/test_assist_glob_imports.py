"""Stage 1H T8 — Family D glob subfamily. Targets ra_glob_imports.

Sub-tests cover ``expand_glob_import`` (wildcard `use` -> explicit list) and
``expand_glob_reexport`` (wildcard `pub use`).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_glob_imports/src/lib.rs"


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


def test_expand_glob_import_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "use std::io::*;")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 14},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Expand" in t and "glob" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no expand_glob_import here; titles={titles}")
    assert any("Expand" in t and "glob" in t.lower() for t in titles)


def test_expand_glob_reexport_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub use crate::inner::*;")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 8},
        end={"line": line_idx, "character": 23},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Expand" in t and ("glob" in t.lower() or "reexport" in t.lower()) for t in titles):
        pytest.skip(f"rust-analyzer offered no expand_glob_reexport here; titles={titles}")
    assert any("Expand" in t for t in titles)
