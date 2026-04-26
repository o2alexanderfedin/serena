"""T5 — _dedup() Stage-2 normalized-title + WorkspaceEdit-equality dedup."""

from __future__ import annotations

import pytest

from serena.refactoring.multi_server import (
    _dedup,
    _normalize_title,
    _workspace_edits_equal,
)


# ---------------------------------------------------------------------------
# Title normalization.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Import 'numpy'", "import 'numpy'"),
    ("Add import: numpy", "import: numpy"),
    ("Quick fix: Add import 'numpy'", "import 'numpy'"),
    ("Add: numpy", "numpy"),
    ("  organize   imports  ", "organize imports"),
    ("Organize Imports", "organize imports"),
    ("", ""),
])
def test_normalize_title(raw: str, expected: str) -> None:
    assert _normalize_title(raw) == expected


# ---------------------------------------------------------------------------
# WorkspaceEdit structural equality (lazy second-pass equality).
# ---------------------------------------------------------------------------

def _edit(uri: str, sl: int, sc: int, el: int, ec: int, txt: str) -> dict:
    return {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}},
                        "newText": txt,
                    }
                ],
            }
        ]
    }


def test_workspace_edits_equal_identical() -> None:
    a = _edit("file:///x.py", 0, 0, 0, 5, "hello")
    b = _edit("file:///x.py", 0, 0, 0, 5, "hello")
    assert _workspace_edits_equal(a, b) is True


def test_workspace_edits_equal_different_text() -> None:
    a = _edit("file:///x.py", 0, 0, 0, 5, "hello")
    b = _edit("file:///x.py", 0, 0, 0, 5, "world")
    assert _workspace_edits_equal(a, b) is False


def test_workspace_edits_equal_different_uri() -> None:
    a = _edit("file:///x.py", 0, 0, 0, 5, "hello")
    b = _edit("file:///y.py", 0, 0, 0, 5, "hello")
    assert _workspace_edits_equal(a, b) is False


def test_workspace_edits_equal_unordered_edits() -> None:
    """Two edits to the same file in different list order MUST equal —
    structural equality is set-of-tuples, not list-equality."""
    a = {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///x.py", "version": None},
                "edits": [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}, "newText": "A"},
                    {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 1}}, "newText": "B"},
                ],
            }
        ]
    }
    b = {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///x.py", "version": None},
                "edits": [
                    {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 1}}, "newText": "B"},
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}, "newText": "A"},
                ],
            }
        ]
    }
    assert _workspace_edits_equal(a, b) is True


def test_workspace_edits_equal_handles_legacy_changes_map() -> None:
    """Some servers ship the legacy ``changes`` map instead of
    ``documentChanges``. Equality must normalize both shapes."""
    a = {"changes": {"file:///x.py": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}}, "newText": "hello"}]}}
    b = _edit("file:///x.py", 0, 0, 0, 5, "hello")
    assert _workspace_edits_equal(a, b) is True


# ---------------------------------------------------------------------------
# _dedup() — composes title equality + lazy structural equality.
# ---------------------------------------------------------------------------

def test_dedup_title_match() -> None:
    cands = [
        ("ruff", {"title": "Import numpy", "kind": "quickfix", "edit": _edit("file:///x.py", 0, 0, 0, 0, "import numpy\n")}),
        ("basedpyright", {"title": "Add import numpy", "kind": "quickfix", "edit": _edit("file:///x.py", 0, 0, 0, 0, "import numpy\n")}),
    ]
    priority = ("ruff", "basedpyright")
    out = _dedup(cands, priority)
    assert len(out) == 1
    sid, _, dropped = out[0]
    assert sid == "ruff"
    assert len(dropped) == 1
    assert dropped[0][0] == "basedpyright"
    assert dropped[0][2] == "duplicate_title"


def test_dedup_edit_match_when_titles_differ() -> None:
    cands = [
        ("ruff", {"title": "Sort imports", "kind": "source.organizeImports.ruff", "edit": _edit("file:///x.py", 0, 0, 5, 0, "X")}),
        ("pylsp-rope", {"title": "Organize imports (Rope)", "kind": "source.organizeImports", "edit": _edit("file:///x.py", 0, 0, 5, 0, "X")}),
    ]
    priority = ("ruff", "pylsp-rope")
    out = _dedup(cands, priority)
    assert len(out) == 1
    sid, _, dropped = out[0]
    assert sid == "ruff"
    assert dropped[0][2] == "duplicate_edit"


def test_dedup_no_match_keeps_both() -> None:
    cands = [
        ("ruff", {"title": "Sort imports", "kind": "source.organizeImports.ruff", "edit": _edit("file:///x.py", 0, 0, 5, 0, "X")}),
        ("pylsp-rope", {"title": "Extract function", "kind": "refactor.extract", "edit": _edit("file:///x.py", 1, 0, 1, 5, "Y")}),
    ]
    priority = ("ruff", "pylsp-rope")
    out = _dedup(cands, priority)
    assert len(out) == 2
    assert {sid for sid, _, _ in out} == {"ruff", "pylsp-rope"}
    assert all(dropped == [] for _, _, dropped in out)


def test_dedup_tiebreak_prefers_higher_priority_server() -> None:
    """If two candidates from servers NOT yet in priority order have the
    same title, the one whose server appears first in the priority
    tuple wins."""
    cands = [
        ("basedpyright", {"title": "Add import: numpy", "kind": "quickfix", "edit": _edit("file:///x.py", 0, 0, 0, 0, "import numpy\n")}),
        ("pylsp-rope", {"title": "Import 'numpy'", "kind": "quickfix", "edit": _edit("file:///x.py", 0, 0, 0, 0, "import numpy\n")}),
    ]
    priority = ("basedpyright", "pylsp-rope")  # auto-import row order
    out = _dedup(cands, priority)
    assert len(out) == 1
    assert out[0][0] == "basedpyright"


def test_dedup_empty_returns_empty() -> None:
    assert _dedup([], priority=("ruff",)) == []


def test_dedup_single_candidate_passes_through() -> None:
    cands = [("ruff", {"title": "x", "kind": "source.organizeImports.ruff", "edit": _edit("file:///x.py", 0, 0, 1, 0, "Y")})]
    out = _dedup(cands, priority=("ruff",))
    assert len(out) == 1
    assert out[0][2] == []
