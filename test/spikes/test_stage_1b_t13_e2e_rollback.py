"""T13 — end-to-end: complex WorkspaceEdit + checkpoint restore + transaction rollback.

Boots no LSP child process; uses LanguageServerCodeEditor.__new__ to build a
test-mode applier whose project_root is a tmp_path. Exercises every applier
op + the refactoring stores together.

Composes T1-T12 end-to-end. No production code changes — proves the substrate
works as a coherent unit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from serena.code_editor import LanguageServerCodeEditor
from serena.refactoring.checkpoints import CheckpointStore
from serena.refactoring.transactions import TransactionStore

from .test_stage_1b_t1_text_document_edit import _FakeLanguageServer


@pytest.fixture
def applier(tmp_path: Path) -> LanguageServerCodeEditor:
    """Test-mode applier: project_root = tmp_path, fake LSP for buffer ops.

    Reuses ``_FakeLanguageServer`` from T1 so TextDocumentEdits actually
    touch disk via the real ``edited_file_context`` flow (which delegates to
    ``_get_language_server`` for buffer + apply_text_edits_to_file).
    """
    inst = LanguageServerCodeEditor.__new__(LanguageServerCodeEditor)
    inst.project_root = str(tmp_path)
    inst.encoding = "utf-8"
    inst.newline = "\n"
    fake_ls = _FakeLanguageServer(str(tmp_path), "utf-8")
    inst._get_language_server = MagicMock(return_value=fake_ls)  # type: ignore[method-assign]
    return inst


def test_complex_multi_shape_edit_then_checkpoint_restore(
    applier: LanguageServerCodeEditor, tmp_path: Path
) -> None:
    """Apply a 4-op WorkspaceEdit, capture checkpoint, restore, assert pre-state."""
    # --- pre-state ---
    edit_target = tmp_path / "edit.txt"
    edit_target.write_text("hello world\n", encoding="utf-8")
    rename_src = tmp_path / "old.txt"
    rename_src.write_text("rename me\n", encoding="utf-8")
    delete_target = tmp_path / "doomed.txt"
    delete_target.write_text("deleted soon\n", encoding="utf-8")

    create_target = tmp_path / "fresh.txt"
    rename_dst = tmp_path / "new.txt"

    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": edit_target.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 6},
                            "end": {"line": 0, "character": 11},
                        },
                        "newText": "there",
                    }
                ],
            },
            {"kind": "create", "uri": create_target.as_uri()},
            {"kind": "rename", "oldUri": rename_src.as_uri(), "newUri": rename_dst.as_uri()},
            {"kind": "delete", "uri": delete_target.as_uri()},
        ]
    }

    report = applier._apply_workspace_edit_with_report(cast(Any, edit))
    assert report["count"] == 4

    # --- post-apply assertions ---
    assert edit_target.read_text(encoding="utf-8") == "hello there\n"
    assert create_target.exists() and create_target.read_text(encoding="utf-8") == ""
    assert not rename_src.exists()
    assert rename_dst.read_text(encoding="utf-8") == "rename me\n"
    assert not delete_target.exists()

    # --- record checkpoint + restore ---
    store = CheckpointStore()
    cid = store.record(edit, report["snapshot"])
    ok = store.restore(cid, cast(Any, applier._apply_workspace_edit))
    assert ok is True

    # --- post-restore assertions: filesystem back to pre-state ---
    assert edit_target.read_text(encoding="utf-8") == "hello world\n"
    assert not create_target.exists()
    assert rename_src.read_text(encoding="utf-8") == "rename me\n"
    assert not rename_dst.exists()
    assert delete_target.read_text(encoding="utf-8") == "deleted soon\n"


def test_three_sequential_edits_transaction_rollback(
    applier: LanguageServerCodeEditor, tmp_path: Path
) -> None:
    """Three independent applies, each captured as a checkpoint inside one transaction.

    rollback walks them in reverse. Resulting filesystem matches initial pre-state.
    """
    a = tmp_path / "a.txt"
    a.write_text("A0\n", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("B0\n", encoding="utf-8")
    c = tmp_path / "c.txt"
    c.write_text("C0\n", encoding="utf-8")

    cstore = CheckpointStore()
    tstore = TransactionStore(checkpoint_store=cstore)
    tid = tstore.begin()

    for path, new in [(a, "A1"), (b, "B1"), (c, "C1")]:
        edit: dict[str, Any] = {
            "documentChanges": [
                {
                    "textDocument": {"uri": path.as_uri(), "version": None},
                    "edits": [
                        {
                            "range": {
                                "start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 2},
                            },
                            "newText": new,
                        }
                    ],
                }
            ]
        }
        report = applier._apply_workspace_edit_with_report(cast(Any, edit))
        cid = cstore.record(edit, report["snapshot"])
        tstore.add_checkpoint(tid, cid)

    assert a.read_text(encoding="utf-8") == "A1\n"
    assert b.read_text(encoding="utf-8") == "B1\n"
    assert c.read_text(encoding="utf-8") == "C1\n"

    n = tstore.rollback(tid, cast(Any, applier._apply_workspace_edit))
    assert n == 3
    assert a.read_text(encoding="utf-8") == "A0\n"
    assert b.read_text(encoding="utf-8") == "B0\n"
    assert c.read_text(encoding="utf-8") == "C0\n"
