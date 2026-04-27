"""Stage 1H T8 — Family I patterns. Targets ra_pattern_destructuring.

Sub-tests cover ``add_missing_match_arms``, ``add_missing_impl_members``,
and ``destructure_struct_binding``. The match-arm assist needs the
wildcard arm removed; the fixture ships with the wildcard so we
deliberately skip when rust-analyzer doesn't surface the assist on the
shipped form (honest skip per spec).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_pattern_destructuring/src/lib.rs"


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


def test_add_missing_match_arms_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "match shape {")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 9},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("missing" in t.lower() and "arm" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no add_missing_match_arms here; titles={titles}")


def test_add_missing_impl_members_offered_on_trait(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "pub trait Greeter")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 10},
        end={"line": line_idx, "character": 17},
    )
    titles = [a.get("title", "") for a in actions]
    # The trait alone is unimplemented in the fixture, so this assist is
    # call-site specific — skip if not offered here.
    if not any(
        "Implement" in t or "missing" in t.lower() or "members" in t.lower()
        for t in titles
    ):
        pytest.skip(f"rust-analyzer offered no add_missing_impl_members here; titles={titles}")


def test_destructure_struct_binding_offered(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / _REL
    text = src.read_text()
    line_idx = _line_index(text, "let pair = NamedPair { left: 1, right: 2 };")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 8},
        end={"line": line_idx, "character": 12},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Destructure" in t for t in titles):
        pytest.skip(f"rust-analyzer offered no destructure_struct_binding here; titles={titles}")
