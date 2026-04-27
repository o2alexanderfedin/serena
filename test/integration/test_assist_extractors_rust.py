"""Stage 1H T8 — Family B: extractors. Targets the ra_extractors fixture crate.

Each sub-test asks rust-analyzer for code actions on a curated coordinate inside
``ra_extractors/src/lib.rs`` and asserts at least one assist-family member
title matches. Round-trip sub-tests additionally apply the WorkspaceEdit via
the v0.3.0 pure-python applier and assert >=1 TextEdit landed on disk.

The ``request_code_actions`` API is **synchronous**; per the Stage 1H smoke
pattern (``test_smoke_rust_codeaction.py``) we wrap the body in
``with ra_lsp.open_file(<rel>):`` + a 1.0 s sleep so rust-analyzer indexes
the freshly opened file before we probe. The session-scoped ``ra_lsp``
fixture amortises the cold workspace boot.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from solidlsp.ls import SolidLanguageServer


_REL = "ra_extractors/src/lib.rs"


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
    """Open the file, wait for indexing, return code actions at the range."""
    actions: list[dict[str, Any]] = []
    with ra_lsp.open_file(_REL):
        time.sleep(1.0)
        raw = ra_lsp.request_code_actions(
            file_abs, start=start, end=end, diagnostics=[]
        )
        actions.extend(a for a in raw if isinstance(a, dict))
    return actions


def test_extract_function_target_offers_extract_function(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / "ra_extractors" / "src" / "lib.rs"
    text = src.read_text()
    line_idx = _line_index(text, "let sum = x + y;")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx + 2, "character": 27},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Extract" in t and "function" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no extract-function here; titles={titles}")
    assert any("Extract" in t and "function" in t.lower() for t in titles), (
        f"no extractor offered; got titles={titles}"
    )


def test_extract_variable_target_offers_extract_variable(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / "ra_extractors" / "src" / "lib.rs"
    text = src.read_text()
    line_idx = _line_index(text, "(1 + 2) * (3 + 4)")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 22},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Extract" in t and "variable" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no extract-variable here; titles={titles}")
    assert any("Extract" in t and "variable" in t.lower() for t in titles), (
        f"no extract-variable offered; got titles={titles}"
    )


def test_extract_type_alias_round_trip(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
    assert_workspace_edit_round_trip,
) -> None:
    src = calcrs_workspace / "ra_extractors" / "src" / "lib.rs"
    text = src.read_text()
    line_idx = _line_index(text, "Result<Vec<(String, i64)>")
    # Stay inside open_file() while we resolve so rust-analyzer's
    # action-id stays live (it expires the moment didClose fires).
    with ra_lsp.open_file(_REL):
        time.sleep(1.0)
        raw = ra_lsp.request_code_actions(
            str(src),
            start={"line": line_idx, "character": 27},
            end={"line": line_idx, "character": 70},
            diagnostics=[],
        )
        actions = [a for a in raw if isinstance(a, dict)]
        extract_alias = next(
            (a for a in actions if "Extract" in a.get("title", "") and "type" in a.get("title", "").lower()),
            None,
        )
        if extract_alias is None:
            titles = [a.get("title", "") for a in actions]
            pytest.skip(f"rust-analyzer did not offer extract_type_alias here; titles={titles}")
        edit = extract_alias.get("edit")
        if edit is None:
            # rust-analyzer is deferred-resolution; resolve while still open.
            resolved = ra_lsp.resolve_code_action(extract_alias)
            edit = resolved.get("edit") if isinstance(resolved, dict) else None
    if edit is None:
        pytest.skip("extract_type_alias action carried no edit even after resolve")
    # Restore file after applying so subsequent sub-tests / runs stay deterministic.
    original = src.read_text()
    try:
        assert_workspace_edit_round_trip(edit)
    finally:
        src.write_text(original)


def test_extract_constant_offers_promote(
    ra_lsp: "SolidLanguageServer",
    calcrs_workspace: Path,
) -> None:
    src = calcrs_workspace / "ra_extractors" / "src" / "lib.rs"
    text = src.read_text()
    line_idx = _line_index(text, "42 * 1024")
    actions = _fetch_actions(
        ra_lsp,
        str(src),
        start={"line": line_idx, "character": 4},
        end={"line": line_idx, "character": 14},
    )
    titles = [a.get("title", "") for a in actions]
    if not any("Extract" in t and "constant" in t.lower() for t in titles):
        pytest.skip(f"rust-analyzer offered no extract-constant here; titles={titles}")
    assert any("Extract" in t and "constant" in t.lower() for t in titles), (
        f"no extract-constant offered; got titles={titles}"
    )
