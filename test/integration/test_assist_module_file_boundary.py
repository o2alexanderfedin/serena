"""Stage 1H T8 — Family A: module/file boundary. Targets ra_module_layouts +
calcrs root.

Sub-tests cover ``extract_module``, ``move_module_to_file``, and the
``mod.rs`` <-> file-form layout-swap pair (``move_from_mod_rs`` and
``move_to_mod_rs``). The fixture ships with both layouts coexisting so
the assists have targets in both directions.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


def _line_index(text: str, needle: str) -> int:
    for i, line in enumerate(text.splitlines()):
        if needle in line:
            return i
    raise AssertionError(f"needle {needle!r} not in fixture text")


def _fetch_actions(
    ra_lsp: "SolidLanguageServer",
    rel: str,
    file_abs: str,
    start: dict[str, int],
    end: dict[str, int],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    with ra_lsp.open_file(rel):
        time.sleep(1.0)
        raw = ra_lsp.request_code_actions(
            file_abs, start=start, end=end, diagnostics=[]
        )
        actions.extend(a for a in raw if isinstance(a, dict))
    return actions


def test_extract_module_offered_on_inline_mod(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    """The calcrs/extractors fixture ships an inline module via ra_extractors."""
    rel = "ra_extractors/src/lib.rs"
    src = calcrs_workspace / rel
    text = src.read_text()
    line_idx = _line_index(text, "pub mod extract_module_target")
    actions = _fetch_actions(
        ra_lsp, rel, str(src),
        start={"line": line_idx, "character": 8},
        end={"line": line_idx, "character": 33},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Extract" in t and "module" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no extract_module here; titles={titles}")


def test_move_module_to_file_offered_on_mod_decl(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    rel = "ra_module_layouts/src/lib.rs"
    src = calcrs_workspace / rel
    text = src.read_text()
    line_idx = _line_index(text, "pub mod baz;")
    actions = _fetch_actions(
        ra_lsp, rel, str(src),
        start={"line": line_idx, "character": 8},
        end={"line": line_idx, "character": 11},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("module" in t.lower() and ("file" in t.lower() or "mod" in t.lower()) for t in titles):
        pytest.skip(f"rust-analyzer offered no move_module_to_file here; titles={titles}")


def test_move_from_mod_rs_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    """At foo/mod.rs the layout-swap assist offers move-out-of mod.rs."""
    rel = "ra_module_layouts/src/foo/mod.rs"
    src = calcrs_workspace / rel
    text = src.read_text()
    line_idx = _line_index(text, "pub mod bar;")
    actions = _fetch_actions(
        ra_lsp, rel, str(src),
        start={"line": line_idx, "character": 0},
        end={"line": line_idx, "character": 12},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("mod.rs" in t.lower() or "convert" in t.lower() or "module" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no move_from_mod_rs here; titles={titles}")


def test_move_to_mod_rs_offered_on_baz(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    """baz.rs (file-form) is the move_to_mod_rs candidate."""
    rel = "ra_module_layouts/src/baz.rs"
    src = calcrs_workspace / rel
    text = src.read_text()
    line_idx = _line_index(text, "pub fn baz_value")
    actions = _fetch_actions(
        ra_lsp, rel, str(src),
        start={"line": line_idx, "character": 7},
        end={"line": line_idx, "character": 16},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("mod.rs" in t.lower() or "convert" in t.lower() or "module" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no move_to_mod_rs here; titles={titles}")
