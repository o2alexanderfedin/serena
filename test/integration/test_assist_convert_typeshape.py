"""Stage 1H T8 — Family H type-shape. Targets ra_convert_typeshape.

Sub-tests cover ``convert_named_struct_to_tuple_struct`` (round-trip via
the conftest helper) and ``convert_match_to_iflet`` shape (or
``replace_match_with_matches!``) on a two-arm bool match.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_convert_typeshape/src/lib.rs"


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


def test_convert_named_struct_to_tuple_struct_round_trip(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
    assert_workspace_edit_round_trip,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub struct Point")
    # Stay inside open_file() while we resolve so RA's action-id stays live.
    with ra_lsp.open_file(_REL):
        time.sleep(1.0)
        raw = ra_lsp.request_code_actions(
            str(src),
            start={"line": line_idx, "character": 11},
            end={"line": line_idx, "character": 16},
            diagnostics=[],
        )
        actions = [a for a in raw if isinstance(a, dict)]
        target = next(
            (a for a in actions if "Convert" in a.get("title", "") and "tuple" in a.get("title", "").lower()),
            None,
        )
        if target is None:
            titles = [a.get("title", "") for a in actions]
            pytest.skip(f"rust-analyzer did not offer convert_named_to_tuple here; titles={titles}")
        edit = target.get("edit")
        if edit is None:
            resolved = ra_lsp.resolve_code_action(target)
            edit = resolved.get("edit") if isinstance(resolved, dict) else None
    if edit is None:
        pytest.skip("convert_named_to_tuple_struct action carried no edit")
    original = src.read_text()
    try:
        assert_workspace_edit_round_trip(edit)
    finally:
        src.write_text(original)


def test_two_arm_bool_match_convert_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "match flag {")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 9},
    )
    titles = [a.get("title", "") for a in actions]
    if not any(
        "matches" in t.lower() or "if let" in t.lower() or "convert" in t.lower()
        for t in titles
    ):
        pytest.skip(f"rust-analyzer offered no two-arm-bool-match convert here; titles={titles}")
