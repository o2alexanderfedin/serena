"""Checkpoint store + inverse WorkspaceEdit synthesis (Stage 1B §4.1).

A ``Checkpoint`` snapshots one successfully-applied ``WorkspaceEdit`` plus the
synthesised inverse. ``CheckpointStore.restore(id)`` re-feeds the inverse
through the same applier (so atomic snapshot + workspace-boundary checks
apply uniformly). LRU(50) eviction by insertion order; thread-safe via
``threading.Lock``.

v1.1 Stream 5 / Leaf 02 adds an OPTIONAL durable disk layer behind the
LRU. ``CheckpointStore(disk_root=<path>)`` mirrors every ``record`` to a
``DiskCheckpointStore`` (one JSON file per checkpoint) and falls back to
disk on LRU miss. Construction is lazy — no eager disk scan; an LRU miss
is the only path that touches disk. ``disk_root=None`` is preserved as a
test-only override (S3 guard); production callers MUST pass a disk root
so checkpoints survive process restart (Leaf 06 depends on this).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .checkpoint_disk import DiskCheckpointStore
from .checkpoint_schema import PersistedCheckpoint

# Sentinels mirror code_editor.py snapshot conventions.
_SNAPSHOT_NONEXISTENT = "__NONEXISTENT__"
_SNAPSHOT_DIRECTORY = "__DIRECTORY__"


def inverse_workspace_edit(
    applied: dict[str, Any],
    snapshot: dict[str, str],
) -> dict[str, Any]:
    """Compute the inverse of a successfully-applied WorkspaceEdit.

    Rules:
    - TextDocumentEdit → DeleteFile(ignoreIfNotExists=True) +
      CreateFile(overwrite=True) + TextDocumentEdit inserting the snapshot
      content at (0,0). Geometry-independent: by deleting and recreating
      the file empty, the subsequent insert at (0,0) writes the entire
      original content regardless of how the applied edits reshaped the
      mutated buffer.
    - CreateFile → DeleteFile (always with no flags; Stage 1B applier deletes
      the file the create just made).
    - DeleteFile → CreateFile(overwrite=True) + TextDocumentEdit inserting
      the snapshot content at (0,0). The freshly-created file is empty so
      inserting at (0,0) writes the full original content.
    - RenameFile → RenameFile with oldUri/newUri swapped.
    - Order is reversed so e.g. a Create→Rename→Delete sequence inverts
      to Create-of-deleted → Rename-back → Delete-of-created.

    :param applied: the applied WorkspaceEdit (legacy ``changes`` map first
        normalised into ``documentChanges`` by the applier before calling).
    :param snapshot: per-URI prior-content map captured during apply.
    :return: WorkspaceEdit-shaped dict with documentChanges in reverse order.
    """
    document_changes: list[dict[str, Any]] = list(applied.get("documentChanges", []))
    inv: list[dict[str, Any]] = []
    for change in reversed(document_changes):
        kind = change.get("kind")
        if kind is None:
            uri = change["textDocument"]["uri"]
            original = snapshot.get(uri, "")
            if original == _SNAPSHOT_NONEXISTENT:
                # File didn't exist before; the inverse of writing into it is delete.
                inv.append({"kind": "delete", "uri": uri})
            else:
                # TextDocumentEdit inverse: delete the (mutated) file, recreate
                # empty, insert the original content at (0,0). Geometry-
                # independent — no need to know the mutated file's actual EOF.
                inv.append({"kind": "delete", "uri": uri, "options": {"ignoreIfNotExists": True}})
                inv.append({"kind": "create", "uri": uri, "options": {"overwrite": True}})
                inv.append(_insert_full_content(uri, original))
        elif kind == "create":
            inv.append({"kind": "delete", "uri": change["uri"]})
        elif kind == "delete":
            uri = change["uri"]
            original = snapshot.get(uri, "")
            if original == _SNAPSHOT_DIRECTORY:
                # Best effort: re-create empty directory marker; deep tree
                # restoration is out of scope (deferred to v1.1 disk checkpoints).
                inv.append({"kind": "create", "uri": uri})
            else:
                inv.append({"kind": "create", "uri": uri, "options": {"overwrite": True}})
                inv.append(_insert_full_content(uri, original))
        elif kind == "rename":
            inv.append({"kind": "rename", "oldUri": change["newUri"], "newUri": change["oldUri"]})
        else:
            raise ValueError(f"Cannot invert unknown documentChange kind: {kind!r}")
    return {"documentChanges": inv}


def _insert_full_content(uri: str, content: str) -> dict[str, Any]:
    """Build a TextDocumentEdit that INSERTS ``content`` at (0, 0).

    Geometry-independent: the range is start==end==(0,0), so the file's
    current size doesn't matter. Use this AFTER a CreateFile(overwrite=True)
    that produces an empty target — the insert then writes the entire
    desired content.
    """
    return {
        "textDocument": {"uri": uri, "version": None},
        "edits": [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 0},
                },
                "newText": content,
            }
        ],
    }


class Checkpoint:
    """One stored applied edit + its inverse, ready for restore.

    v1.1: ``created_at_ns`` records monotonic creation time, used by the
    disk layer's FIFO retention. ``to_persisted`` / ``from_persisted``
    bridge to ``PersistedCheckpoint`` for cross-session durability;
    ``from_persisted`` bypasses ``__init__`` (which would recompute the
    inverse from ``applied``/``snapshot``) and rehydrates the stored
    inverse directly.
    """

    __slots__ = ("id", "applied", "snapshot", "inverse", "created_at_ns")

    def __init__(
        self,
        applied: dict[str, Any],
        snapshot: dict[str, str],
    ) -> None:
        self.id: str = uuid.uuid4().hex
        self.applied: dict[str, Any] = applied
        self.snapshot: dict[str, str] = snapshot
        self.inverse: dict[str, Any] = inverse_workspace_edit(applied, snapshot)
        # time.monotonic_ns is preferred for ordering (immune to wall-clock
        # adjustments) and matches the disk layer's FIFO-by-mtime semantics
        # in spirit. Stored on the in-memory object so ``to_persisted`` is a
        # cheap projection.
        self.created_at_ns: int = time.monotonic_ns()

    def to_persisted(self) -> PersistedCheckpoint:
        """Project to the on-disk schema. Lossy on ``applied``/``snapshot`` —
        only ``inverse`` is needed by ``CheckpointStore.restore``."""
        return PersistedCheckpoint(
            id=self.id,
            schema_version=1,
            created_at_ns=self.created_at_ns,
            inverse_edit=self.inverse,
            file_versions={},  # reserved for v1.2 stale-detection (Leaf 06)
        )

    @classmethod
    def from_persisted(cls, persisted: PersistedCheckpoint) -> Checkpoint:
        """Rehydrate from disk. Bypasses ``__init__`` so we can install the
        stored inverse directly instead of re-deriving it from empty
        ``applied``/``snapshot`` placeholders.

        Downstream of ``CheckpointStore.restore`` only ``inverse`` is read
        (see ``transactions.py``, ``scalpel_primitives.py``), so leaving
        ``applied`` and ``snapshot`` as empty dicts is sound."""
        ckpt = cls.__new__(cls)
        ckpt.id = persisted.id
        ckpt.applied = {}
        ckpt.snapshot = {}
        ckpt.inverse = dict(persisted.inverse_edit)
        ckpt.created_at_ns = persisted.created_at_ns
        return ckpt


class CheckpointStore:
    """In-memory LRU(50) of Checkpoints over an OPTIONAL disk durable layer.

    Thread-safe. LRU eviction by insertion-order (OrderedDict.move_to_end
    on successful access keeps recently-used at the tail) is independent
    of the disk-side FIFO retention — the LRU is the hot-path cache; the
    disk store is the source of truth for cross-session restore.

    v1.1 contract:

    - ``disk_root=None`` (test-only override) preserves Stage 1B semantics:
      pure in-memory store, no persistence.
    - ``disk_root=<path>``: every ``record`` mirrors to disk; ``get`` on
      LRU miss falls back to disk and rehydrates into the LRU; ``evict``
      propagates to disk so explicit drops are durable.
    - Construction is lazy — no eager disk scan, no eager load. The first
      LRU miss is the only thing that hits disk.
    - LRU eviction does NOT delete from disk (disk has its own retention).

    Per critic S3 (spec lines 174-178): production callers MUST receive a
    disk_root from settings. ``None`` is the test-override only. Bypassing
    persistence in production breaks Leaf 06's pending-tx survival.
    """

    DEFAULT_CAPACITY = 50

    def __init__(
        self,
        capacity: int = DEFAULT_CAPACITY,
        disk_root: Path | None = None,
    ) -> None:
        self._store: OrderedDict[str, Checkpoint] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()
        self._disk: DiskCheckpointStore | None = (
            DiskCheckpointStore(disk_root) if disk_root is not None else None
        )

    def record(
        self,
        applied: dict[str, Any],
        snapshot: dict[str, str],
    ) -> str:
        """Record a successful apply; return checkpoint id.

        Writes through to disk (if configured) AFTER the LRU insert so a
        disk-write failure cannot leave the LRU and disk inconsistent in
        the LRU's favour — ``record`` is best-effort durable: the in-memory
        path always succeeds; disk failure surfaces only on a later get
        fallback when the in-memory entry has been LRU-evicted. (For v1.1
        we accept this; v1.2 may add fsync + write-fence.)
        """
        ckpt = Checkpoint(applied, snapshot)
        with self._lock:
            self._store[ckpt.id] = ckpt
            self._evict_lru()
        if self._disk is not None:
            self._disk.put(ckpt.to_persisted())
        return ckpt.id

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Look up a checkpoint by id (touches LRU recency).

        On LRU miss with ``disk_root`` configured, attempts a lazy disk
        read; on success, the rehydrated checkpoint is reinserted into
        the LRU (subject to eviction) so subsequent ``get`` calls hit
        memory. Disk-rehydrated entries do NOT re-mirror to disk — they
        are already there.
        """
        with self._lock:
            ckpt = self._store.get(checkpoint_id)
            if ckpt is not None:
                self._store.move_to_end(checkpoint_id)
                return ckpt
        # LRU miss → lazy disk fallback.
        if self._disk is None:
            return None
        persisted = self._disk.get(checkpoint_id)
        if persisted is None:
            return None
        rehydrated = Checkpoint.from_persisted(persisted)
        with self._lock:
            # Another caller may have populated the slot between miss and
            # rehydration — keep the existing entry to preserve identity.
            existing = self._store.get(checkpoint_id)
            if existing is not None:
                self._store.move_to_end(checkpoint_id)
                return existing
            self._store[checkpoint_id] = rehydrated
            self._evict_lru()
        return rehydrated

    def restore(
        self,
        checkpoint_id: str,
        applier_fn: Callable[[dict[str, Any]], int],
    ) -> bool:
        """Re-apply the stored inverse via ``applier_fn``.

        :param checkpoint_id: id returned by ``record``.
        :param applier_fn: typically ``LanguageServerCodeEditor._apply_workspace_edit``.
            Returns the count of operations applied; restore returns True iff
            count > 0.
        """
        ckpt = self.get(checkpoint_id)
        if ckpt is None:
            return False
        n = applier_fn(ckpt.inverse)
        return n > 0

    def evict(self, checkpoint_id: str) -> bool:
        """Drop a checkpoint by id (used by TransactionStore cascade evict).

        Propagates to disk so the drop is durable. Returns True if either
        layer had the entry — matches Stage 1B "True on any successful
        removal" semantics."""
        with self._lock:
            in_mem = self._store.pop(checkpoint_id, None) is not None
        on_disk = False
        if self._disk is not None:
            on_disk = self._disk.evict(checkpoint_id)
        return in_mem or on_disk

    def __len__(self) -> int:
        """Return the in-memory LRU size. Disk size is independent and
        not reflected here — callers wanting total durable count should
        introspect the disk store directly."""
        with self._lock:
            return len(self._store)

    def _evict_lru(self) -> None:
        """Caller holds self._lock. LRU eviction does NOT touch disk."""
        while len(self._store) > self._capacity:
            self._store.popitem(last=False)
