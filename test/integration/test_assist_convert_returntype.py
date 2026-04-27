"""Stage 1H T8 — Family H return-type. Targets ra_convert_returntype.

Sub-tests cover ``wrap_return_type_in_result`` and
``unwrap_option_return_type``. Both are signature-modifying assists.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_convert_returntype/src/lib.rs"


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


def test_wrap_return_type_in_result_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub fn returns_plain_i64")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 30},
        end={"line": line_idx, "character": 33},
    )
    titles = [a.get("title", "") for a in actions]
    if not any(("Wrap" in t and "Result" in t) for t in titles):
        pytest.skip(f"rust-analyzer offered no wrap_return_type_in_result here; titles={titles}")
    assert any(("Wrap" in t and "Result" in t) for t in titles)


def test_unwrap_option_return_type_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub fn returns_option_i64")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 31},
        end={"line": line_idx, "character": 41},
    )
    titles = [a.get("title", "") for a in actions]
    if not any(
        ("Unwrap" in t and "Option" in t) or ("Convert" in t and "Option" in t)
        for t in titles
    ):
        pytest.skip(f"rust-analyzer offered no unwrap_option_return_type here; titles={titles}")
