"""T11 — end-to-end three-server fake fixture replay (P2 + P6 + auto-import).

Adapted from plan to fit actual T0-T10 API surface. Validates the full
broadcast → normalize → priority → dedup → resolve → invariants → log
pipeline on the actual MultiServerCoordinator built in T1-T10.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from serena.refactoring.multi_server import (
    EditAttributionLog,
    MultiServerCoordinator,
)


# ---------------------------------------------------------------------------
# P2 — pylsp-rope vs ruff on source.organizeImports — ruff wins per §11.1
# ---------------------------------------------------------------------------

_P2_PYLSP_ROPE_ACTION_WITH_EDIT = {
    "title": "Organize Imports",
    "kind": "source.organizeImports",
    "edit": {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///fake/calcpy/__init__.py", "version": None},
                "edits": [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 3, "character": 0}}, "newText": "from typing import Final\n"},
                ],
            }
        ]
    },
}

_P2_RUFF_ACTION = {
    "title": "Ruff: Organize imports",
    "kind": "source.organizeImports.ruff",
    "edit": {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///fake/calcpy/__init__.py", "version": None},
                "edits": [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 3, "character": 0}}, "newText": "import os\nimport sys\nfrom typing import List\n"},
                ],
            }
        ]
    },
}


@pytest.mark.asyncio
async def test_p2_organize_imports_ruff_wins_pylsp_dropped(fake_pool):
    fake_pool["pylsp-rope"].code_actions = [_P2_PYLSP_ROPE_ACTION_WITH_EDIT]
    fake_pool["ruff"].code_actions = [_P2_RUFF_ACTION]
    fake_pool["basedpyright"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["source.organizeImports"],
    )
    assert len(merged) == 1
    assert merged[0].provenance == "ruff"
    assert merged[0].suppressed_alternatives == []  # debug merge OFF


@pytest.mark.asyncio
async def test_p2_with_debug_merge_records_pylsp_in_suppressed_alternatives(
    fake_pool, monkeypatch
):
    monkeypatch.setenv("O2_SCALPEL_DEBUG_MERGE", "1")
    fake_pool["pylsp-rope"].code_actions = [_P2_PYLSP_ROPE_ACTION_WITH_EDIT]
    fake_pool["ruff"].code_actions = [_P2_RUFF_ACTION]
    fake_pool["basedpyright"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["source.organizeImports"],
    )
    assert len(merged) == 1
    assert merged[0].provenance == "ruff"
    suppressed_provs = {s.provenance for s in merged[0].suppressed_alternatives}
    assert "pylsp-rope" in suppressed_provs
    assert any(s.reason == "lower_priority" for s in merged[0].suppressed_alternatives)


# ---------------------------------------------------------------------------
# P6 — pylsp whole-file rename vs basedpyright surgical — pylsp wins per §11.3
# ---------------------------------------------------------------------------

_P6_PYLSP_RENAME = {
    "documentChanges": [
        {
            "textDocument": {"uri": "file:///fake/calcpy/__init__.py", "version": None},
            "edits": [
                {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 19, "character": 0}},
                 "newText": '"""Minimal seed package used by Phase 0 spikes."""\nfrom typing import Final\n\nVERSION: Final = "0.0.0"\n\n\ndef plus(a: int, b: int) -> int:\n    return a + b\n\n\ndef mul(a: int, b: int) -> int:\n    return a * b\n\n\ndef _private_helper(x: int) -> int:\n    return -x\n\n\n__all__ = ["VERSION", "add", "mul"]\n'},
            ],
        },
    ]
}

_P6_BASEDPYRIGHT_RENAME = {
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
async def test_p6_rename_pylsp_wins(fake_pool, monkeypatch):
    monkeypatch.delenv("O2_SCALPEL_DEBUG_MERGE", raising=False)
    fake_pool["pylsp-rope"].rename_edit = _P6_PYLSP_RENAME
    fake_pool["basedpyright"].rename_edit = _P6_BASEDPYRIGHT_RENAME
    coord = MultiServerCoordinator(fake_pool)
    edit, warnings = await coord.merge_rename(
        relative_file_path="calcpy/__init__.py",
        line=6, column=4, new_name="plus",
    )
    assert edit == _P6_PYLSP_RENAME
    assert warnings == []  # debug OFF → no secondary call


@pytest.mark.asyncio
async def test_p6_with_debug_merge_emits_provenance_disagreement(fake_pool, monkeypatch):
    monkeypatch.setenv("O2_SCALPEL_DEBUG_MERGE", "1")
    fake_pool["pylsp-rope"].rename_edit = _P6_PYLSP_RENAME
    fake_pool["basedpyright"].rename_edit = _P6_BASEDPYRIGHT_RENAME
    coord = MultiServerCoordinator(fake_pool)
    edit, warnings = await coord.merge_rename(
        relative_file_path="calcpy/__init__.py",
        line=6, column=4, new_name="plus",
    )
    assert edit == _P6_PYLSP_RENAME
    assert len(warnings) == 1
    w = warnings[0]
    assert w["kind"] == "provenance.disagreement"
    assert w["winner"] == "pylsp-rope"
    assert w["loser"] == "basedpyright"
    assert "symdiff" in w


# ---------------------------------------------------------------------------
# Auto-import organic quickfix — basedpyright sole responder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_import_quickfix_basedpyright_provenance(fake_pool, tmp_path):
    target = tmp_path / "user.py"
    target.write_text("x = numpy.array([])\n", encoding="utf-8")
    auto_import_action = {
        "title": 'Import "numpy"',
        "kind": "quickfix",
        "edit": {
            "documentChanges": [
                {
                    "textDocument": {"uri": target.as_uri(), "version": None},
                    "edits": [
                        {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "newText": "import numpy\n"},
                    ],
                }
            ]
        },
    }
    fake_pool["pylsp-rope"].code_actions = []
    fake_pool["ruff"].code_actions = []
    fake_pool["basedpyright"].code_actions = [auto_import_action]
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file=str(target),
        start={"line": 0, "character": 4},
        end={"line": 0, "character": 9},
        only=["quickfix"],
        diagnostics=[{"code": "reportUndefinedVariable", "message": "name 'numpy' is not defined",
                      "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 9}}}],
    )
    # Per §11.1 quickfix (auto-import context): basedpyright > pylsp-rope.
    assert len(merged) == 1
    assert merged[0].provenance == "basedpyright"
    assert merged[0].title == 'Import "numpy"'


# ---------------------------------------------------------------------------
# Edit-attribution log replay round-trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_replay_round_trip_after_three_merges(tmp_path):
    target = tmp_path / "u.py"
    target.write_text("x = 1\n", encoding="utf-8")
    edit = {
        "documentChanges": [
            {"textDocument": {"uri": target.as_uri(), "version": None},
             "edits": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}}, "newText": "y = 2"}]}
        ]
    }
    log = EditAttributionLog(project_root=tmp_path)
    for i in range(3):
        await log.append(checkpoint_id=f"ckpt_{i}", tool="scalpel_apply_capability",
                         server="ruff", edit=edit)
    records = list(log.replay())
    assert len(records) == 3
    assert {r["checkpoint_id"] for r in records} == {"ckpt_0", "ckpt_1", "ckpt_2"}
    assert all(r["server"] == "ruff" for r in records)
