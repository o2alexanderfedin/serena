"""T8 — merge_rename() §11.3 single-primary + P6 reconciliation."""

from __future__ import annotations

from pathlib import Path

import pytest

from serena.refactoring.multi_server import (
    MultiServerCoordinator,
    _reconcile_rename_edits,
)


# P6 spike fixture payloads (literal — see spike-results/P6.md).
P6_PYLSP_EDIT = {
    "documentChanges": [
        {
            "textDocument": {"uri": "file:///fake/calcpy/__init__.py", "version": None},
            "edits": [
                {
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 19, "character": 0}},
                    "newText": '"""Minimal seed package used by Phase 0 spikes."""\nfrom typing import Final\n\nVERSION: Final = "0.0.0"\n\n\ndef plus(a: int, b: int) -> int:\n    return a + b\n\n\ndef mul(a: int, b: int) -> int:\n    return a * b\n\n\ndef _private_helper(x: int) -> int:\n    return -x\n\n\n__all__ = ["VERSION", "add", "mul"]\n',
                }
            ],
        },
        {
            "textDocument": {"uri": "file:///fake/calcpy/__main__.py", "version": None},
            "edits": [
                {
                    "range": {"start": {"line": 0, "character": 0}, "end": {"line": 4, "character": 0}},
                    "newText": 'from . import plus\n\nif __name__ == "__main__":\n    print(plus(2, 3))\n',
                }
            ],
        },
    ]
}

P6_BASEDPYRIGHT_EDIT = {
    "documentChanges": [
        {
            "textDocument": {"uri": "file:///fake/calcpy/__init__.py", "version": None},
            "edits": [
                {"range": {"start": {"line": 6, "character": 4}, "end": {"line": 6, "character": 7}}, "newText": "plus"},
                {"range": {"start": {"line": 18, "character": 23}, "end": {"line": 18, "character": 26}}, "newText": "plus"},
            ],
        }
    ]
}


@pytest.mark.asyncio
async def test_merge_rename_pylsp_only_when_debug_unset(fake_pool, monkeypatch):
    monkeypatch.delenv("O2_SCALPEL_DEBUG_MERGE", raising=False)
    fake_pool["pylsp-rope"].rename_edit = P6_PYLSP_EDIT
    fake_pool["basedpyright"].rename_edit = P6_BASEDPYRIGHT_EDIT
    coord = MultiServerCoordinator(fake_pool)
    edit, warnings = await coord.merge_rename(
        relative_file_path="calcpy/__init__.py",
        line=6, column=4, new_name="plus",
    )
    assert edit == P6_PYLSP_EDIT
    assert warnings == []
    # basedpyright was NOT called.
    assert not any(c[0] == "request_rename_symbol_edit" for c in fake_pool["basedpyright"].calls)


@pytest.mark.asyncio
async def test_merge_rename_emits_disagreement_warning_when_debug_set(fake_pool, monkeypatch):
    monkeypatch.setenv("O2_SCALPEL_DEBUG_MERGE", "1")
    fake_pool["pylsp-rope"].rename_edit = P6_PYLSP_EDIT
    fake_pool["basedpyright"].rename_edit = P6_BASEDPYRIGHT_EDIT
    coord = MultiServerCoordinator(fake_pool)
    edit, warnings = await coord.merge_rename(
        relative_file_path="calcpy/__init__.py",
        line=6, column=4, new_name="plus",
    )
    assert edit == P6_PYLSP_EDIT  # pylsp still wins
    assert len(warnings) == 1
    w = warnings[0]
    assert w["kind"] == "provenance.disagreement"
    assert w["winner"] == "pylsp-rope"
    assert w["loser"] == "basedpyright"
    assert "symdiff" in w
    # P6: only_in_pylsp=2, only_in_basedpyright=2 (whole-file vs surgical).
    assert w["symdiff"]["only_in_winner"] >= 1
    assert w["symdiff"]["only_in_loser"] >= 1


@pytest.mark.asyncio
async def test_merge_rename_handles_basedpyright_none_gracefully(fake_pool, monkeypatch):
    monkeypatch.setenv("O2_SCALPEL_DEBUG_MERGE", "1")
    fake_pool["pylsp-rope"].rename_edit = P6_PYLSP_EDIT
    fake_pool["basedpyright"].rename_edit = None
    coord = MultiServerCoordinator(fake_pool)
    edit, warnings = await coord.merge_rename(
        relative_file_path="calcpy/__init__.py",
        line=6, column=4, new_name="plus",
    )
    assert edit == P6_PYLSP_EDIT
    # disagreement warning still emitted with loser_returned_none=True
    assert len(warnings) == 1
    assert warnings[0]["loser_returned_none"] is True


@pytest.mark.asyncio
async def test_merge_rename_returns_none_when_pylsp_returns_none(fake_pool):
    fake_pool["pylsp-rope"].rename_edit = None
    coord = MultiServerCoordinator(fake_pool)
    edit, warnings = await coord.merge_rename(
        relative_file_path="calcpy/__init__.py",
        line=6, column=4, new_name="plus",
    )
    assert edit is None
    assert warnings == []


# ---------------------------------------------------------------------------
# _reconcile_rename_edits — whole-file vs surgical normalization.
# ---------------------------------------------------------------------------

def test_reconcile_whole_file_to_surgical_via_difflib(tmp_path: Path) -> None:
    """Given a pylsp whole-file replacement and the source file, produce
    a list of (uri, surgical_text_edit) tuples comparable to basedpyright's
    output. Uses difflib.unified_diff line-mapping per Phase 0 SUMMARY §4
    P6 row."""
    f = tmp_path / "x.py"
    f.write_text("def add():\n    pass\n", encoding="utf-8")
    pylsp_whole = {
        "documentChanges": [
            {
                "textDocument": {"uri": f.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 2, "character": 0}},
                        "newText": "def plus():\n    pass\n",
                    }
                ],
            }
        ]
    }
    surgical_tuples = _reconcile_rename_edits(pylsp_whole, source_reader=lambda _: f.read_text(encoding="utf-8"))
    # The reconciliation should isolate the changed line.
    uris = {t[0] for t in surgical_tuples}
    assert uris == {f.as_uri()}
    # At least one tuple should reference the renamed token.
    assert any("plus" in t[1].get("newText", "") for t in surgical_tuples)


def test_reconcile_passthrough_for_already_surgical(tmp_path: Path) -> None:
    """basedpyright-shaped edits pass through verbatim."""
    f = tmp_path / "x.py"
    f.write_text("x = add()\n", encoding="utf-8")
    surgical = {
        "documentChanges": [
            {
                "textDocument": {"uri": f.as_uri(), "version": None},
                "edits": [
                    {"range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 7}}, "newText": "plus"},
                ],
            }
        ]
    }
    out = _reconcile_rename_edits(surgical, source_reader=lambda _: f.read_text(encoding="utf-8"))
    assert len(out) == 1
    uri, te = out[0]
    assert uri == f.as_uri()
    assert te["newText"] == "plus"
