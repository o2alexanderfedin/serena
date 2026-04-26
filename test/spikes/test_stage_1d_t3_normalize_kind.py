"""T3 — _normalize_kind() Phase 0 P2 sub-kind collapse.

Maps hierarchical leaf kinds (server-suffixed) onto the base family
key the §11.1 priority table is keyed against."""

from __future__ import annotations

import pytest

from serena.refactoring.multi_server import _normalize_kind


@pytest.mark.parametrize("raw,expected", [
    # P2 finding: ruff suffix hierarchy.
    ("source.organizeImports.ruff", "source.organizeImports"),
    ("source.fixAll.ruff", "source.fixAll"),
    # Same hierarchical shape with other servers (defensive — Stage 1E
    # may register additional adapters that follow the same convention).
    ("source.organizeImports.pylsp-rope", "source.organizeImports"),
    ("source.fixAll.basedpyright", "source.fixAll"),
    # Bare kinds pass through unchanged — they're the base families.
    ("source.organizeImports", "source.organizeImports"),
    ("source.fixAll", "source.fixAll"),
    ("quickfix", "quickfix"),
    ("refactor.extract", "refactor.extract"),
    ("refactor.inline", "refactor.inline"),
    ("refactor.rewrite", "refactor.rewrite"),
    ("refactor", "refactor"),
    ("source", "source"),
    # LSP §3.18.1 grandchild that isn't server-suffixed (e.g.
    # rust-analyzer's ``refactor.extract.module``) MUST NOT collapse —
    # those are real semantic sub-actions, not server-tag suffixes.
    ("refactor.extract.module", "refactor.extract.module"),
    ("refactor.extract.function", "refactor.extract.function"),
])
def test_normalize_kind_table(raw: str, expected: str) -> None:
    assert _normalize_kind(raw) == expected


def test_normalize_kind_empty_string_passes_through() -> None:
    assert _normalize_kind("") == ""


def test_normalize_kind_unknown_kind_passes_through() -> None:
    """Per §11.2 row "kind: null/unrecognized" → bucket as quickfix.other.
    That bucketing is _apply_priority's job; _normalize_kind itself is
    pure-string and just normalizes server-suffixes."""
    assert _normalize_kind("vendor.custom.thing") == "vendor.custom.thing"


def test_normalize_kind_preserves_dots_in_unknown_segments() -> None:
    """A multi-segment kind we don't recognize as a server-suffix shape
    must pass through verbatim (no aggressive trim)."""
    assert _normalize_kind("source.organizeImports.unknownVendor") == "source.organizeImports.unknownVendor"
