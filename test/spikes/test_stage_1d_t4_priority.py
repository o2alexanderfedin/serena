"""T4 — _apply_priority() §11.1 priority table per kind family."""

from __future__ import annotations

import pytest

from serena.refactoring.multi_server import (
    _apply_priority,
    _classify_quickfix_context,
)


def _ca(server: str, kind: str, title: str = "x", **extra) -> tuple[str, dict]:
    base = {"title": title, "kind": kind}
    base.update(extra)
    return (server, base)


# ---------------------------------------------------------------------------
# Priority-table — one assertion per row of the §11.1 table.
# ---------------------------------------------------------------------------

def test_organize_imports_ruff_beats_rope_beats_basedpyright() -> None:
    cands = [
        _ca("pylsp-rope", "source.organizeImports"),
        _ca("ruff", "source.organizeImports.ruff"),
        _ca("basedpyright", "source.organizeImports"),
    ]
    winners = _apply_priority(cands, family="source.organizeImports", quickfix_context=None)
    assert [s for s, _ in winners] == ["ruff"]


def test_source_fix_all_unique_ruff() -> None:
    cands = [_ca("ruff", "source.fixAll.ruff")]
    winners = _apply_priority(cands, family="source.fixAll", quickfix_context=None)
    assert [s for s, _ in winners] == ["ruff"]


def test_quickfix_auto_import_basedpyright_beats_rope() -> None:
    cands = [
        _ca("pylsp-rope", "quickfix"),
        _ca("basedpyright", "quickfix"),
    ]
    winners = _apply_priority(cands, family="quickfix", quickfix_context="auto-import")
    assert [s for s, _ in winners] == ["basedpyright"]


def test_quickfix_lint_ruff_beats_rope_beats_basedpyright() -> None:
    cands = [
        _ca("ruff", "quickfix"),
        _ca("pylsp-rope", "quickfix"),
        _ca("basedpyright", "quickfix"),
    ]
    winners = _apply_priority(cands, family="quickfix", quickfix_context="lint-fix")
    assert [s for s, _ in winners] == ["ruff"]


def test_quickfix_type_error_basedpyright_only_pylsp_mypy_excluded() -> None:
    """pylsp-mypy is DROPPED at MVP per Phase 0 P5a / SUMMARY §6; merger
    never sees it. Row collapses to basedpyright-only."""
    cands = [_ca("basedpyright", "quickfix")]
    winners = _apply_priority(cands, family="quickfix", quickfix_context="type-error")
    assert [s for s, _ in winners] == ["basedpyright"]


def test_quickfix_other_rope_beats_basedpyright_beats_ruff() -> None:
    cands = [
        _ca("pylsp-rope", "quickfix"),
        _ca("basedpyright", "quickfix"),
        _ca("ruff", "quickfix"),
    ]
    winners = _apply_priority(cands, family="quickfix", quickfix_context="other")
    assert [s for s, _ in winners] == ["pylsp-rope"]


def test_refactor_extract_unique_rope() -> None:
    cands = [_ca("pylsp-rope", "refactor.extract")]
    winners = _apply_priority(cands, family="refactor.extract", quickfix_context=None)
    assert [s for s, _ in winners] == ["pylsp-rope"]


def test_refactor_inline_unique_rope() -> None:
    cands = [_ca("pylsp-rope", "refactor.inline")]
    winners = _apply_priority(cands, family="refactor.inline", quickfix_context=None)
    assert [s for s, _ in winners] == ["pylsp-rope"]


def test_refactor_rewrite_rope_beats_basedpyright() -> None:
    cands = [
        _ca("basedpyright", "refactor.rewrite"),
        _ca("pylsp-rope", "refactor.rewrite"),
    ]
    winners = _apply_priority(cands, family="refactor.rewrite", quickfix_context=None)
    assert [s for s, _ in winners] == ["pylsp-rope"]


def test_refactor_catchall_rope_beats_basedpyright() -> None:
    cands = [
        _ca("pylsp-rope", "refactor"),
        _ca("basedpyright", "refactor"),
    ]
    winners = _apply_priority(cands, family="refactor", quickfix_context=None)
    assert [s for s, _ in winners] == ["pylsp-rope"]


def test_source_catchall_ruff_beats_rope_beats_basedpyright() -> None:
    cands = [
        _ca("pylsp-rope", "source"),
        _ca("ruff", "source"),
        _ca("basedpyright", "source"),
    ]
    winners = _apply_priority(cands, family="source", quickfix_context=None)
    assert [s for s, _ in winners] == ["ruff"]


# ---------------------------------------------------------------------------
# §11.2 cross-cases that touch _apply_priority directly.
# ---------------------------------------------------------------------------

def test_disabled_action_preserved_even_when_lower_priority() -> None:
    """§11.2 row "Server returns disabled.reason set" — preserve in
    merged list. _apply_priority surfaces it alongside the winner."""
    cands = [
        _ca("ruff", "source.organizeImports.ruff"),
        _ca("pylsp-rope", "source.organizeImports", disabled={"reason": "no-imports-to-organize"}),
    ]
    winners = _apply_priority(cands, family="source.organizeImports", quickfix_context=None)
    sids = [s for s, _ in winners]
    assert "ruff" in sids
    assert "pylsp-rope" in sids  # disabled candidate preserved
    rope_action = [a for s, a in winners if s == "pylsp-rope"][0]
    assert rope_action.get("disabled", {}).get("reason") == "no-imports-to-organize"


def test_unknown_server_falls_to_lowest_priority() -> None:
    """A candidate from a server not in the priority table for the
    family lands at the END of the winners list (or is dropped if
    higher-priority candidates exist for the same family)."""
    cands = [
        _ca("ruff", "source.organizeImports.ruff"),
        _ca("vendor-x", "source.organizeImports"),  # unknown server
    ]
    winners = _apply_priority(cands, family="source.organizeImports", quickfix_context=None)
    assert [s for s, _ in winners] == ["ruff"]


def test_no_candidates_returns_empty() -> None:
    assert _apply_priority([], family="quickfix", quickfix_context="other") == []


# ---------------------------------------------------------------------------
# Quickfix context classifier.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    # pylsp-rope ``rope_autoimport`` → basedpyright also emits → auto-import bucket.
    ("undefined-name", "auto-import"),
    ("reportUndefinedVariable", "auto-import"),
    ("F401", "lint-fix"),  # ruff's "imported but unused"
    ("E501", "lint-fix"),  # ruff line-length
    ("reportArgumentType", "type-error"),
    ("reportCallIssue", "type-error"),
    ("reportInvalidTypeForm", "type-error"),
    ("unknown-thing", "other"),
    (None, "other"),
])
def test_classify_quickfix_context(code: object, expected: str) -> None:
    diag = {"code": code} if code is not None else {}
    assert _classify_quickfix_context(diag) == expected
