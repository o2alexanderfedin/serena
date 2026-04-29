"""v1.6 PR 2 / Plan 1 — Real snapshot capture + apply_action_and_checkpoint.

RED tests:
1. ``test_capture_pre_edit_snapshot_for_existing_file`` — given a workspace
   edit that touches an existing file, the helper reads the file's pre-edit
   bytes and returns ``{uri: content}``.
2. ``test_capture_pre_edit_snapshot_for_create_file_resource_op`` — a
   ``documentChanges`` entry with ``kind="create"`` yields the
   ``_SNAPSHOT_NONEXISTENT`` sentinel for the URI.
3. ``test_capture_pre_edit_snapshot_for_delete_file_resource_op`` — same
   for ``kind="delete"`` (post-state is "doesn't exist"; pre-state is also
   captured as the sentinel because the helper's role is "what was there
   before" — and for delete ops the LSP edit doesn't carry the prior bytes).
4. ``test_capture_pre_edit_snapshot_for_rename_file_resource_op`` — the
   OLD URI's content is snapshotted; the NEW URI is left out.
5. ``test_capture_pre_edit_snapshot_handles_text_document_edit_shape`` —
   ``documentChanges`` with ``textDocument`` shape (no ``kind``) is treated
   like a ``changes`` entry.
6. ``test_capture_pre_edit_snapshot_for_missing_file_uses_sentinel`` —
   when the URI is a ``file://`` URI but the file is absent on disk, fall
   back to the ``_SNAPSHOT_NONEXISTENT`` sentinel.
7. ``test_apply_action_and_checkpoint_records_real_snapshot`` — full path:
   resolve winner edit, capture snapshot of pre-edit content, apply to
   disk, record checkpoint. Assert the checkpoint store has the snapshot.
8. ``test_apply_action_and_checkpoint_no_op_when_resolved_edit_empty`` —
   ``_resolve_winner_edit`` returns ``None``; helper returns
   ``("", {"changes": {}})``; no disk write.

Plan source: docs/superpowers/plans/2026-04-29-stub-facade-fix/IMPLEMENTATION-PLANS.md  Plan 1
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.tools.facade_support import (
    _SNAPSHOT_NONEXISTENT,
    apply_action_and_checkpoint,
    capture_pre_edit_snapshot,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# capture_pre_edit_snapshot tests
# ---------------------------------------------------------------------------


def _file_uri(path: Path) -> str:
    return path.as_uri()


def test_capture_pre_edit_snapshot_for_existing_file(tmp_path: Path) -> None:
    src = tmp_path / "hello.txt"
    src.write_text("hello\n", encoding="utf-8")
    edit = {
        "changes": {
            _file_uri(src): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "HELLO",
                }
            ]
        }
    }
    snap = capture_pre_edit_snapshot(edit)
    assert snap == {_file_uri(src): "hello\n"}


def test_capture_pre_edit_snapshot_for_create_file_resource_op(tmp_path: Path) -> None:
    new_uri = _file_uri(tmp_path / "brand_new.py")
    edit = {
        "documentChanges": [
            {"kind": "create", "uri": new_uri},
        ]
    }
    snap = capture_pre_edit_snapshot(edit)
    assert snap == {new_uri: _SNAPSHOT_NONEXISTENT}


def test_capture_pre_edit_snapshot_for_delete_file_resource_op(tmp_path: Path) -> None:
    target = tmp_path / "doomed.py"
    target.write_text("# bye\n", encoding="utf-8")
    edit = {
        "documentChanges": [
            {"kind": "delete", "uri": _file_uri(target)},
        ]
    }
    snap = capture_pre_edit_snapshot(edit)
    # Post-state is "doesn't exist"; the helper's snapshot intent for delete
    # ops is symmetrical with create — the pre-edit content is captured as
    # the sentinel because the LSP delete-op doesn't carry a payload.
    assert snap == {_file_uri(target): _SNAPSHOT_NONEXISTENT}


def test_capture_pre_edit_snapshot_for_rename_file_resource_op(tmp_path: Path) -> None:
    old = tmp_path / "old.py"
    old.write_text("old content\n", encoding="utf-8")
    new_uri = _file_uri(tmp_path / "new.py")
    edit = {
        "documentChanges": [
            {"kind": "rename", "oldUri": _file_uri(old), "newUri": new_uri},
        ]
    }
    snap = capture_pre_edit_snapshot(edit)
    # The OLD URI's pre-edit content is preserved; the NEW URI is not in
    # the snapshot because no pre-edit content existed there.
    assert snap == {_file_uri(old): "old content\n"}


def test_capture_pre_edit_snapshot_handles_text_document_edit_shape(tmp_path: Path) -> None:
    src = tmp_path / "doc.py"
    src.write_text("doc content\n", encoding="utf-8")
    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": _file_uri(src), "version": 1},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 3},
                        },
                        "newText": "DOC",
                    }
                ],
            }
        ]
    }
    snap = capture_pre_edit_snapshot(edit)
    assert snap == {_file_uri(src): "doc content\n"}


def test_capture_pre_edit_snapshot_for_missing_file_uses_sentinel(tmp_path: Path) -> None:
    """If the URI points at a file that doesn't exist, snapshot is sentinel."""
    missing = tmp_path / "does_not_exist.py"
    edit = {
        "changes": {
            _file_uri(missing): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 0},
                    },
                    "newText": "x",
                }
            ]
        }
    }
    snap = capture_pre_edit_snapshot(edit)
    assert snap == {_file_uri(missing): _SNAPSHOT_NONEXISTENT}


# ---------------------------------------------------------------------------
# apply_action_and_checkpoint tests
# ---------------------------------------------------------------------------


class _FakeAction:
    def __init__(self, action_id: str) -> None:
        self.id = action_id


class _FakeCoordinator:
    """Test double with the ``get_action_edit`` lookup that
    ``_resolve_winner_edit`` requires."""

    def __init__(self, edits: dict[str, dict[str, Any]] | None = None) -> None:
        self._edits = edits or {}

    def get_action_edit(self, aid: str) -> dict[str, Any] | None:
        return self._edits.get(aid)


@pytest.fixture(autouse=True)
def _isolate_runtime():
    """Reset the ScalpelRuntime singleton + override its checkpoint store
    with an in-memory one (no disk persistence) so the test is hermetic."""
    ScalpelRuntime.reset_for_testing()
    inst = ScalpelRuntime.instance()
    # Pre-populate with an in-memory checkpoint store (disk_root=None).
    # Bypasses the lazy disk-rooted factory in
    # ``ScalpelRuntime.checkpoint_store``.
    inst._checkpoint_store = CheckpointStore(disk_root=None)
    yield
    ScalpelRuntime.reset_for_testing()


def test_apply_action_and_checkpoint_records_real_snapshot(tmp_path: Path) -> None:
    src = tmp_path / "lib.py"
    src.write_text("ALPHA\n", encoding="utf-8")
    uri = _file_uri(src)
    edit = {
        "changes": {
            uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "BETA",
                }
            ]
        }
    }
    coord = _FakeCoordinator(edits={"a1": edit})
    action = _FakeAction("a1")

    cid, applied = apply_action_and_checkpoint(coord, action)

    # Disk was written to (post-edit content, not pre-edit content).
    assert src.read_text(encoding="utf-8") == "BETA\n"
    # Returned applied edit echoes the resolved edit.
    assert applied == edit
    # Checkpoint id is non-empty and the store has the real snapshot.
    assert cid != ""
    ckpt = ScalpelRuntime.instance().checkpoint_store().get(cid)
    assert ckpt is not None
    assert ckpt.snapshot == {uri: "ALPHA\n"}
    assert ckpt.applied == edit


def test_apply_action_and_checkpoint_no_op_when_resolved_edit_empty(
    tmp_path: Path,
) -> None:
    src = tmp_path / "lib.py"
    src.write_text("UNCHANGED\n", encoding="utf-8")
    coord = _FakeCoordinator(edits={})  # No edit registered.
    action = _FakeAction("missing")

    cid, applied = apply_action_and_checkpoint(coord, action)

    # No disk write.
    assert src.read_text(encoding="utf-8") == "UNCHANGED\n"
    # Resolve-failure branch: ``applied`` is the empty-edit fallback,
    # but per the v0.2.0 contract a checkpoint is still recorded so the
    # caller's ``payload["checkpoint_id"]`` stays truthy.
    assert applied == {"changes": {}}
    assert cid != ""
    ckpt = ScalpelRuntime.instance().checkpoint_store().get(cid)
    assert ckpt is not None
    assert ckpt.applied == {"changes": {}}
    assert ckpt.snapshot == {}
