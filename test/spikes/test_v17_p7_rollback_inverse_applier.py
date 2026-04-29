"""v1.7 PR 7 / Plan 3-A — REAL inverse-applier for rollback.

Replaces the v1.6-era ``_no_op_applier`` with an inverse-applier that restores
files to disk from the captured pre-edit snapshot. v1.6 PR 1 (snapshot capture)
+ PR 2 (apply_action_and_checkpoint) provide the prerequisite snapshot data;
this PR closes the rollback contract.

RED tests:

1. ``test_inverse_applier_restores_textedit_content`` — fixture file ``hello``;
   snapshot ``{uri: "hello"}``; applied_edit modified to ``"hello world"``; call
   inverse; assert file is back to ``"hello"``.
2. ``test_inverse_applier_restores_create_to_nonexistent`` — file at
   ``/tmp/created.py``; snapshot ``{uri: _SNAPSHOT_NONEXISTENT}``; applied_edit
   had ``kind="create"``; call inverse; assert file no longer exists.
3. ``test_inverse_applier_handles_rename_reversal`` — fixture had ``old.py`` with
   ``"a"``, applied_edit renamed to ``new.py`` with content ``"b"``; snapshot
   ``{old_uri: "a"}``; call inverse; assert ``old.py`` exists with ``"a"`` and
   ``new.py`` deleted.
4. ``test_inverse_applier_skips_delete_op_with_warning`` — ``kind="delete"`` and
   snapshot is ``_SNAPSHOT_NONEXISTENT`` (impossible to restore); call inverse;
   assert returns warning and original delete stands.
5. ``test_rollback_tool_calls_inverse_applier_then_marks_reverted`` — full
   integration; assert disk restored AND store says reverted.
6. ``test_transaction_rollback_walks_steps_in_reverse_order`` — 3-step
   transaction; rollback in REVERSE chronological order so dependent edits
   unwind cleanly.

Plan source: docs/superpowers/plans/2026-04-29-stub-facade-fix/over-plan.md  Plan 3-A
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.tools.facade_support import (
    _SNAPSHOT_NONEXISTENT,
    _inverse_applier_to_disk,
    inverse_apply_checkpoint,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _file_uri(path: Path) -> str:
    return path.as_uri()


def _build_single_rollback(project_root: Path):  # type: ignore[no-untyped-def]
    from serena.tools.scalpel_primitives import ScalpelRollbackTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return ScalpelRollbackTool(agent=agent)


def _build_txn_rollback(project_root: Path):  # type: ignore[no-untyped-def]
    from serena.tools.scalpel_primitives import ScalpelTransactionRollbackTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return ScalpelTransactionRollbackTool(agent=agent)


# ---------------------------------------------------------------------------
# 1. _inverse_applier_to_disk — direct unit tests
# ---------------------------------------------------------------------------


def test_inverse_applier_restores_textedit_content(tmp_path: Path) -> None:
    """A simple TextDocumentEdit's content is restored from the snapshot."""
    src = tmp_path / "hello.txt"
    src.write_text("hello world", encoding="utf-8")  # post-edit content
    uri = _file_uri(src)
    snapshot = {uri: "hello"}  # pre-edit content
    applied_edit: dict[str, Any] = {
        "changes": {
            uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 5},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": " world",
                }
            ]
        }
    }

    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)

    assert ok is True
    assert warnings == []
    assert src.read_text(encoding="utf-8") == "hello"


def test_inverse_applier_restores_create_to_nonexistent(tmp_path: Path) -> None:
    """A ``kind="create"`` op rolls back by deleting the created file."""
    created = tmp_path / "created.py"
    created.write_text("# brand new\n", encoding="utf-8")
    uri = _file_uri(created)
    snapshot = {uri: _SNAPSHOT_NONEXISTENT}
    applied_edit: dict[str, Any] = {
        "documentChanges": [
            {"kind": "create", "uri": uri},
        ]
    }

    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)

    assert ok is True
    assert warnings == []
    assert not created.exists()


def test_inverse_applier_handles_rename_reversal(tmp_path: Path) -> None:
    """A rename old→new is undone by renaming new→old + restoring old's content."""
    old = tmp_path / "old.py"
    new = tmp_path / "new.py"
    # post-edit state: old is gone, new has the post-edit content
    new.write_text("b", encoding="utf-8")
    old_uri = _file_uri(old)
    new_uri = _file_uri(new)
    snapshot = {old_uri: "a"}
    applied_edit: dict[str, Any] = {
        "documentChanges": [
            {"kind": "rename", "oldUri": old_uri, "newUri": new_uri},
        ]
    }

    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)

    assert ok is True
    assert warnings == []
    assert old.exists()
    assert old.read_text(encoding="utf-8") == "a"
    assert not new.exists()


def test_inverse_applier_skips_delete_op_with_warning(tmp_path: Path) -> None:
    """A ``kind="delete"`` op cannot be inverted without captured content;
    return a warning and leave the (already-deleted) file alone."""
    deleted = tmp_path / "deleted.py"
    # post-edit state: file is gone (it was deleted by the applied edit)
    uri = _file_uri(deleted)
    # snapshot is the sentinel because capture_pre_edit_snapshot uses the
    # sentinel for delete-ops (the LSP delete op carries no payload).
    snapshot = {uri: _SNAPSHOT_NONEXISTENT}
    applied_edit: dict[str, Any] = {
        "documentChanges": [
            {"kind": "delete", "uri": uri},
        ]
    }

    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)

    # ok=True (we did what we could), but a warning surfaces the irreversible op.
    assert warnings, "expected a warning for irreversible delete"
    assert any("delete" in w.lower() for w in warnings)
    assert not deleted.exists()  # original delete stands


# ---------------------------------------------------------------------------
# 2. ScalpelRollbackTool integration — real inverse_apply_checkpoint
# ---------------------------------------------------------------------------


def test_rollback_tool_calls_inverse_applier_then_marks_reverted(
    tmp_path: Path,
) -> None:
    """Full integration: tool restores disk AND the store records the
    checkpoint as reverted on the second call."""
    src = tmp_path / "round_trip.py"
    src.write_text("def foo():\n    return 1\n", encoding="utf-8")
    uri = _file_uri(src)
    pre_content = "def foo():\n    return 1\n"
    post_content = "def foo():\n    return 2\n"

    # Apply real edit to disk to mimic post-apply state.
    src.write_text(post_content, encoding="utf-8")

    # Record a checkpoint with the real pre-edit snapshot.
    applied_edit: dict[str, Any] = {
        "changes": {
            uri: [
                {
                    "range": {
                        "start": {"line": 1, "character": 11},
                        "end": {"line": 1, "character": 12},
                    },
                    "newText": "2",
                }
            ]
        }
    }
    snapshot = {uri: pre_content}
    cid = ScalpelRuntime.instance().checkpoint_store().record(
        applied=applied_edit, snapshot=snapshot,
    )

    tool = _build_single_rollback(tmp_path)
    raw = tool.apply(checkpoint_id=cid)
    payload = json.loads(raw)

    # Disk content restored.
    assert src.read_text(encoding="utf-8") == pre_content
    # Store reports applied=True on first rollback.
    assert payload["applied"] is True
    assert payload["no_op"] is False

    # Second call is a no-op.
    raw2 = tool.apply(checkpoint_id=cid)
    payload2 = json.loads(raw2)
    assert payload2["no_op"] is True


def test_transaction_rollback_walks_steps_in_reverse_order(
    tmp_path: Path,
) -> None:
    """3-step transaction; rollback walks reverse chronological order so each
    step's inverse runs against the correct interim state."""
    a = tmp_path / "a.py"
    a.write_text("v3\n", encoding="utf-8")  # post-step-3 state

    uri_a = _file_uri(a)
    rt = ScalpelRuntime.instance()
    txn_id = rt.transaction_store().begin()

    # Step 1: v0 → v1
    cid1 = rt.checkpoint_store().record(
        applied={
            "changes": {
                uri_a: [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 2},
                    },
                    "newText": "v1",
                }],
            }
        },
        snapshot={uri_a: "v0\n"},
    )
    rt.transaction_store().add_checkpoint(txn_id, cid1)

    # Step 2: v1 → v2
    cid2 = rt.checkpoint_store().record(
        applied={
            "changes": {
                uri_a: [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 2},
                    },
                    "newText": "v2",
                }],
            }
        },
        snapshot={uri_a: "v1\n"},
    )
    rt.transaction_store().add_checkpoint(txn_id, cid2)

    # Step 3: v2 → v3
    cid3 = rt.checkpoint_store().record(
        applied={
            "changes": {
                uri_a: [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 2},
                    },
                    "newText": "v3",
                }],
            }
        },
        snapshot={uri_a: "v2\n"},
    )
    rt.transaction_store().add_checkpoint(txn_id, cid3)

    tool = _build_txn_rollback(tmp_path)
    raw = tool.apply(transaction_id=txn_id)
    payload = json.loads(raw)

    assert payload["rolled_back"] is True
    assert len(payload["per_step"]) == 3
    # Final disk state is the pre-step-1 state because step 3 unwinds first
    # (v3→v2), then step 2 (v2→v1), then step 1 (v1→v0).
    assert a.read_text(encoding="utf-8") == "v0\n"


# ---------------------------------------------------------------------------
# 3. inverse_apply_checkpoint — fetches store record + drives applier
# ---------------------------------------------------------------------------


def test_inverse_apply_checkpoint_drives_inverse_from_store(
    tmp_path: Path,
) -> None:
    """The store-fronted helper looks up the checkpoint and calls the
    inverse-applier with the captured snapshot+applied_edit."""
    src = tmp_path / "x.py"
    src.write_text("AFTER", encoding="utf-8")
    uri = _file_uri(src)
    cid = ScalpelRuntime.instance().checkpoint_store().record(
        applied={"changes": {uri: [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 6},
            },
            "newText": "AFTER",
        }]}},
        snapshot={uri: "BEFORE"},
    )
    ok, warnings = inverse_apply_checkpoint(cid)
    assert ok is True
    assert warnings == []
    assert src.read_text(encoding="utf-8") == "BEFORE"


def test_inverse_apply_checkpoint_unknown_id_returns_false(tmp_path: Path) -> None:
    ok, warnings = inverse_apply_checkpoint("ckpt_does_not_exist")
    assert ok is False
    assert warnings == []
