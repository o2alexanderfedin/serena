"""v1.1 Stream 5 / Leaf 02 — cross-session persistence integration tests.

These tests exercise the composed in-memory ``CheckpointStore`` over a
``DiskCheckpointStore`` durable layer. The contract verified here:

1. With ``disk_root=None`` (test-only opt-out), behaviour is unchanged
   from the in-memory-only Stage 1B store.
2. With ``disk_root=<path>``, ``record`` mirrors to disk and ``get``
   falls back to disk on LRU miss.
3. A fresh ``CheckpointStore`` instance pointed at the same disk_root
   can read checkpoints written by a previous instance (the cross-
   session durability guarantee that v1.1 Leaf 06 depends on).
4. LRU eviction does NOT delete from disk — disk has its own FIFO.
5. ``evict`` propagates to disk so explicit drops are durable.

The tests use the existing ``CheckpointStore.record(applied, snapshot)``
API; ``Checkpoint.to_persisted()`` and ``Checkpoint.from_persisted()``
are the new round-trip helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from serena.refactoring.checkpoint_schema import PersistedCheckpoint
from serena.refactoring.checkpoints import Checkpoint, CheckpointStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _edit() -> dict[str, Any]:
    """Minimal applied WorkspaceEdit fixture: one TextDocumentEdit."""
    return {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///x.py", "version": 1},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 0},
                        },
                        "newText": "x = 1\n",
                    }
                ],
            }
        ]
    }


def _snapshot() -> dict[str, str]:
    return {"file:///x.py": "old content\n"}


# ---------------------------------------------------------------------------
# Task 3 — Checkpoint <-> PersistedCheckpoint round-trip
# ---------------------------------------------------------------------------


def test_checkpoint_to_persisted_round_trip() -> None:
    ckpt = Checkpoint(_edit(), _snapshot())
    persisted = ckpt.to_persisted()
    assert isinstance(persisted, PersistedCheckpoint)
    assert persisted.id == ckpt.id
    assert persisted.inverse_edit == ckpt.inverse
    # file_versions reserved for v1.2; empty dict for now.
    assert persisted.file_versions == {}
    assert persisted.created_at_ns >= 0


def test_checkpoint_from_persisted_preserves_inverse() -> None:
    ckpt = Checkpoint(_edit(), _snapshot())
    persisted = ckpt.to_persisted()
    restored = Checkpoint.from_persisted(persisted)
    assert restored.id == ckpt.id
    assert restored.inverse == ckpt.inverse
    # applied/snapshot are NOT consumed downstream of restore — they are
    # left as empty dicts in the from_persisted-built Checkpoint.
    assert restored.applied == {}
    assert restored.snapshot == {}


# ---------------------------------------------------------------------------
# Task 3 — CheckpointStore disk composition
# ---------------------------------------------------------------------------


def test_store_without_disk_root_is_in_memory_only() -> None:
    """disk_root=None (test-only override) must not touch disk."""
    s = CheckpointStore(disk_root=None)
    cid = s.record(_edit(), _snapshot())
    assert s.get(cid) is not None
    # No disk attribute should be active.
    assert s._disk is None  # type: ignore[attr-defined]


def test_store_with_disk_root_mirrors_to_disk(tmp_path: Path) -> None:
    s = CheckpointStore(disk_root=tmp_path)
    cid = s.record(_edit(), _snapshot())
    # File written.
    assert (tmp_path / f"{cid}.json").is_file()


def test_store_lazy_disk_fallback_on_lru_miss(tmp_path: Path) -> None:
    """If LRU evicts a checkpoint, the next get() must read from disk."""
    s = CheckpointStore(capacity=2, disk_root=tmp_path)
    c1 = s.record(_edit(), _snapshot())
    c2 = s.record(_edit(), _snapshot())
    c3 = s.record(_edit(), _snapshot())
    # c1 evicted from LRU (capacity=2), but still on disk.
    assert len(s) == 2
    got = s.get(c1)
    assert got is not None
    assert got.id == c1
    assert got.inverse  # inverse round-tripped through disk
    # c2 + c3 still in LRU.
    assert s.get(c2) is not None
    assert s.get(c3) is not None


def test_store_survives_recreation_via_disk_root(tmp_path: Path) -> None:
    """The cross-session guarantee Leaf 06 depends on."""
    s1 = CheckpointStore(disk_root=tmp_path)
    cid = s1.record(_edit(), _snapshot())
    inverse_before = s1.get(cid).inverse  # type: ignore[union-attr]
    del s1
    # Simulate a process restart — fresh store, same disk root.
    s2 = CheckpointStore(disk_root=tmp_path)
    # No eager load: LRU is empty.
    assert len(s2) == 0
    got = s2.get(cid)
    assert got is not None
    assert got.id == cid
    assert got.inverse == inverse_before


def test_store_init_does_not_eagerly_load(tmp_path: Path) -> None:
    """Per spec line 222: 'No eager disk load at construction (lazy fetch)'."""
    s1 = CheckpointStore(disk_root=tmp_path)
    s1.record(_edit(), _snapshot())
    s1.record(_edit(), _snapshot())
    s2 = CheckpointStore(disk_root=tmp_path)
    # LRU empty until first get().
    assert len(s2) == 0


def test_store_lru_evict_does_not_delete_disk(tmp_path: Path) -> None:
    """LRU eviction policy is independent of disk retention."""
    s = CheckpointStore(capacity=1, disk_root=tmp_path)
    c1 = s.record(_edit(), _snapshot())
    s.record(_edit(), _snapshot())  # evicts c1 from LRU
    # c1 still readable via disk fallback.
    assert s.get(c1) is not None
    assert (tmp_path / f"{c1}.json").is_file()


def test_store_explicit_evict_deletes_disk(tmp_path: Path) -> None:
    """``evict(id)`` is the durable drop path — used by TransactionStore."""
    s = CheckpointStore(disk_root=tmp_path)
    cid = s.record(_edit(), _snapshot())
    assert s.evict(cid) is True
    assert s.get(cid) is None
    assert not (tmp_path / f"{cid}.json").is_file()


def test_store_restore_works_after_lru_eviction(tmp_path: Path) -> None:
    """End-to-end: restore() must succeed for a checkpoint loaded from disk."""
    s = CheckpointStore(capacity=1, disk_root=tmp_path)
    c1 = s.record(_edit(), _snapshot())
    s.record(_edit(), _snapshot())  # evicts c1 from LRU

    applied: list[dict[str, Any]] = []

    def applier(edit: dict[str, Any]) -> int:
        applied.append(edit)
        # Pretend we applied N ops; restore() returns truthy iff > 0.
        return len(edit.get("documentChanges", []))

    ok = s.restore(c1, applier)
    assert ok is True
    assert len(applied) == 1
    assert applied[0]  # the inverse edit was passed through
