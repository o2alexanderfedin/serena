"""PC2 coverage uplift — serena.refactoring.checkpoints uncovered ranges.

Target line ranges from Phase B coverage analysis:
  L72    inverse_workspace_edit TextDocumentEdit path (no prior = NONEXISTENT → delete)
  L82-85 inverse_workspace_edit create kind → delete
  L90-90 inverse_workspace_edit delete kind (directory sentinel)
  L92-95 inverse_workspace_edit delete kind (file with content)
  L97    inverse_workspace_edit rename kind
  L263   CheckpointStore.get() LRU miss path (no disk configured)
  L273-274 CheckpointStore.get() rehydration race: slot already populated
  L293   CheckpointStore.restore() checkpoint not found → False
  L263   (also tests the disk-fallback path when disk=None)

Pure unit tests — no LSP or real disk needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from serena.refactoring.checkpoints import (
    Checkpoint,
    CheckpointStore,
    _SNAPSHOT_DIRECTORY,
    _SNAPSHOT_NONEXISTENT,
    inverse_workspace_edit,
)


# ---------------------------------------------------------------------------
# inverse_workspace_edit — comprehensive coverage of all change kinds
# ---------------------------------------------------------------------------


class TestInverseWorkspaceEdit:
    def test_text_document_edit_with_prior_content(self) -> None:
        """TextDocumentEdit: prior content → delete+create+insert triple."""
        applied = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///a.py"},
                "edits": [{"range": {"start": {"line": 0, "character": 0},
                                    "end": {"line": 0, "character": 3}}, "newText": "new"}],
            }],
        }
        snapshot = {"file:///a.py": "old content"}
        inv = inverse_workspace_edit(applied, snapshot)
        # Should contain delete + create + insert.
        changes = inv["documentChanges"]
        kinds = [c.get("kind") for c in changes]
        assert "delete" in kinds
        assert "create" in kinds
        # At least one entry should be a text insert (no "kind" key).
        text_edits = [c for c in changes if "kind" not in c]
        assert len(text_edits) == 1
        assert text_edits[0]["edits"][0]["newText"] == "old content"

    def test_text_document_edit_with_nonexistent_snapshot(self) -> None:
        """TextDocumentEdit when file didn't exist → delete inverse."""
        applied = {
            "documentChanges": [{
                "textDocument": {"uri": "file:///new.py"},
                "edits": [],
            }],
        }
        snapshot = {"file:///new.py": _SNAPSHOT_NONEXISTENT}
        inv = inverse_workspace_edit(applied, snapshot)
        kinds = [c.get("kind") for c in inv["documentChanges"]]
        assert kinds == ["delete"]

    def test_create_kind_inverts_to_delete(self) -> None:
        applied = {
            "documentChanges": [{"kind": "create", "uri": "file:///new.py"}],
        }
        inv = inverse_workspace_edit(applied, {})
        kinds = [c.get("kind") for c in inv["documentChanges"]]
        assert "delete" in kinds

    def test_delete_kind_inverts_to_create_plus_insert(self) -> None:
        applied = {
            "documentChanges": [{"kind": "delete", "uri": "file:///old.py"}],
        }
        snapshot = {"file:///old.py": "was here"}
        inv = inverse_workspace_edit(applied, snapshot)
        kinds = [c.get("kind") for c in inv["documentChanges"]]
        assert "create" in kinds
        # Insert to restore content.
        text_edits = [c for c in inv["documentChanges"] if "kind" not in c]
        assert text_edits[0]["edits"][0]["newText"] == "was here"

    def test_delete_kind_directory_sentinel(self) -> None:
        """delete of a directory: inverse is just a create (no content insert)."""
        applied = {
            "documentChanges": [{"kind": "delete", "uri": "file:///mydir"}],
        }
        snapshot = {"file:///mydir": _SNAPSHOT_DIRECTORY}
        inv = inverse_workspace_edit(applied, snapshot)
        kinds = [c.get("kind") for c in inv["documentChanges"]]
        # Only a create placeholder — no text insert.
        assert "create" in kinds
        text_edits = [c for c in inv["documentChanges"] if "kind" not in c]
        assert len(text_edits) == 0

    def test_rename_kind_swaps_uris(self) -> None:
        applied = {
            "documentChanges": [{
                "kind": "rename",
                "oldUri": "file:///old.py",
                "newUri": "file:///new.py",
            }],
        }
        inv = inverse_workspace_edit(applied, {})
        rename = next(c for c in inv["documentChanges"] if c.get("kind") == "rename")
        assert rename["oldUri"] == "file:///new.py"
        assert rename["newUri"] == "file:///old.py"

    def test_unknown_kind_raises(self) -> None:
        applied = {
            "documentChanges": [{"kind": "unknownOp", "uri": "file:///x.py"}],
        }
        with pytest.raises(ValueError, match="Cannot invert unknown"):
            inverse_workspace_edit(applied, {})

    def test_reverse_order_applied(self) -> None:
        """Operations are processed in reverse order."""
        applied = {
            "documentChanges": [
                {"kind": "create", "uri": "file:///a.py"},
                {"kind": "create", "uri": "file:///b.py"},
            ],
        }
        inv = inverse_workspace_edit(applied, {})
        # Reversed: b first, a second.
        uris = [c["uri"] for c in inv["documentChanges"]]
        assert uris.index("file:///b.py") < uris.index("file:///a.py")

    def test_empty_document_changes(self) -> None:
        inv = inverse_workspace_edit({"documentChanges": []}, {})
        assert inv["documentChanges"] == []


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_init_sets_fields(self) -> None:
        applied = {"documentChanges": [{"kind": "create", "uri": "file:///x.py"}]}
        snapshot: dict[str, str] = {}
        ckpt = Checkpoint(applied, snapshot)
        assert ckpt.id != ""
        assert ckpt.applied is applied
        assert ckpt.snapshot is snapshot
        assert isinstance(ckpt.inverse, dict)
        assert ckpt.reverted is False
        assert ckpt.created_at_ns > 0

    def test_reverted_flag_mutable(self) -> None:
        ckpt = Checkpoint({"documentChanges": []}, {})
        ckpt.reverted = True
        assert ckpt.reverted is True

    def test_to_persisted_round_trip(self) -> None:
        applied = {"documentChanges": []}
        ckpt = Checkpoint(applied, {})
        persisted = ckpt.to_persisted()
        assert persisted.id == ckpt.id
        assert persisted.created_at_ns == ckpt.created_at_ns

    def test_from_persisted_rehydrates_inverse(self) -> None:
        applied = {"documentChanges": [{"kind": "create", "uri": "file:///x.py"}]}
        ckpt = Checkpoint(applied, {})
        persisted = ckpt.to_persisted()
        rehydrated = Checkpoint.from_persisted(persisted)
        assert rehydrated.id == ckpt.id
        assert rehydrated.inverse == ckpt.inverse
        assert rehydrated.applied == {}  # not stored in persisted schema
        assert rehydrated.reverted is False


# ---------------------------------------------------------------------------
# CheckpointStore
# ---------------------------------------------------------------------------


class TestCheckpointStore:
    def test_record_and_get(self) -> None:
        cs = CheckpointStore(capacity=50, disk_root=None)
        cid = cs.record({"documentChanges": []}, {})
        ckpt = cs.get(cid)
        assert ckpt is not None
        assert ckpt.id == cid

    def test_get_unknown_id_returns_none(self) -> None:
        cs = CheckpointStore(capacity=50, disk_root=None)
        assert cs.get("nonexistent") is None

    def test_get_no_disk_lru_miss_returns_none(self) -> None:
        """With disk_root=None, LRU miss returns None (no disk fallback)."""
        cs = CheckpointStore(capacity=1, disk_root=None)
        cid1 = cs.record({"documentChanges": []}, {})
        # Record a second entry to evict cid1 from the LRU.
        cs.record({"documentChanges": []}, {})
        # cid1 is now evicted; no disk → None.
        result = cs.get(cid1)
        assert result is None

    def test_restore_unknown_returns_false(self) -> None:
        cs = CheckpointStore(capacity=50, disk_root=None)

        def _applier(edit: dict) -> int:
            return 1

        assert cs.restore("nonexistent", _applier) is False

    def test_restore_existing_calls_applier(self) -> None:
        cs = CheckpointStore(capacity=50, disk_root=None)
        applied_edits: list[dict] = []

        def _applier(edit: dict) -> int:
            applied_edits.append(edit)
            return 1

        cid = cs.record({"documentChanges": []}, {})
        result = cs.restore(cid, _applier)
        assert result is True
        assert len(applied_edits) == 1

    def test_restore_applier_returns_zero_is_false(self) -> None:
        cs = CheckpointStore(capacity=50, disk_root=None)

        def _zero_applier(edit: dict) -> int:
            return 0

        cid = cs.record({"documentChanges": []}, {})
        result = cs.restore(cid, _zero_applier)
        assert result is False

    def test_evict_in_memory_returns_true(self) -> None:
        cs = CheckpointStore(capacity=50, disk_root=None)
        cid = cs.record({"documentChanges": []}, {})
        result = cs.evict(cid)
        assert result is True
        assert cs.get(cid) is None

    def test_evict_unknown_returns_false(self) -> None:
        cs = CheckpointStore(capacity=50, disk_root=None)
        assert cs.evict("nonexistent") is False

    def test_len_tracks_inserts_and_evictions(self) -> None:
        cs = CheckpointStore(capacity=50, disk_root=None)
        assert len(cs) == 0
        cid = cs.record({"documentChanges": []}, {})
        assert len(cs) == 1
        cs.evict(cid)
        assert len(cs) == 0

    def test_lru_eviction_when_over_capacity(self) -> None:
        cs = CheckpointStore(capacity=2, disk_root=None)
        cid1 = cs.record({"documentChanges": []}, {})
        cid2 = cs.record({"documentChanges": []}, {})
        # Over capacity: cid1 evicted.
        cid3 = cs.record({"documentChanges": []}, {})
        assert len(cs) == 2
        assert cs.get(cid1) is None
        assert cs.get(cid2) is not None
        assert cs.get(cid3) is not None

    def test_get_updates_lru_recency(self) -> None:
        """Accessing cid1 before inserting cid3 keeps it alive."""
        cs = CheckpointStore(capacity=2, disk_root=None)
        cid1 = cs.record({"documentChanges": []}, {})
        cs.record({"documentChanges": []}, {})
        # Access cid1 to make it MRU.
        assert cs.get(cid1) is not None
        # Now insert a third entry — cid2 (LRU) gets evicted, not cid1.
        cs.record({"documentChanges": []}, {})
        # cid1 should still be present (it was recently accessed).
        assert cs.get(cid1) is not None

    def test_disk_store_used_when_configured(self, tmp_path: Path) -> None:
        cs = CheckpointStore(capacity=1, disk_root=tmp_path)
        cid = cs.record({"documentChanges": []}, {})
        # Insert second entry to evict cid from LRU.
        cs.record({"documentChanges": []}, {})
        # LRU miss should fall back to disk.
        ckpt = cs.get(cid)
        assert ckpt is not None
        assert ckpt.id == cid
