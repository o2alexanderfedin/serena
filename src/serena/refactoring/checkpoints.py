"""Checkpoint store + inverse WorkspaceEdit synthesis (Stage 1B §4.1).

A ``Checkpoint`` snapshots one successfully-applied ``WorkspaceEdit`` plus the
synthesised inverse. ``CheckpointStore.restore(id)`` re-feeds the inverse
through the same applier (so atomic snapshot + workspace-boundary checks
apply uniformly). LRU(50) eviction by insertion order; thread-safe via
``threading.Lock``.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

# Sentinels mirror code_editor.py snapshot conventions.
_SNAPSHOT_NONEXISTENT = "__NONEXISTENT__"
_SNAPSHOT_DIRECTORY = "__DIRECTORY__"


def inverse_workspace_edit(
    applied: dict[str, Any],
    snapshot: dict[str, str],
) -> dict[str, Any]:
    """Compute the inverse of a successfully-applied WorkspaceEdit.

    Rules:
    - TextDocumentEdit → TextDocumentEdit that re-installs ``snapshot[uri]`` via
      a single full-file replacement (range (0,0)..(MAX,MAX)).
    - CreateFile → DeleteFile (always with no flags; Stage 1B applier deletes
      the file the create just made).
    - DeleteFile → CreateFile(overwrite=True) + TextDocumentEdit re-installing
      the snapshot content.
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
                inv.append(_full_file_overwrite(uri, original))
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
                inv.append(_full_file_overwrite(uri, original))
        elif kind == "rename":
            inv.append({"kind": "rename", "oldUri": change["newUri"], "newUri": change["oldUri"]})
        else:
            raise ValueError(f"Cannot invert unknown documentChange kind: {kind!r}")
    return {"documentChanges": inv}


def _full_file_overwrite(uri: str, content: str) -> dict[str, Any]:
    """Build a TextDocumentEdit that replaces the entire file with ``content``."""
    # Use a max-int end position; LSP applier clamps to actual EOF.
    end_line = max(content.count("\n"), 0)
    end_char = len(content.split("\n")[-1]) if content else 0
    return {
        "textDocument": {"uri": uri, "version": None},
        "edits": [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": end_line, "character": end_char},
                },
                "newText": content,
            }
        ],
    }


class Checkpoint:
    """One stored applied edit + its inverse, ready for restore."""

    __slots__ = ("id", "applied", "snapshot", "inverse")

    def __init__(
        self,
        applied: dict[str, Any],
        snapshot: dict[str, str],
    ) -> None:
        self.id: str = uuid.uuid4().hex
        self.applied: dict[str, Any] = applied
        self.snapshot: dict[str, str] = snapshot
        self.inverse: dict[str, Any] = inverse_workspace_edit(applied, snapshot)


class CheckpointStore:
    """In-memory LRU(50) of Checkpoints (§4.1).

    Thread-safe. Eviction by insertion-order (OrderedDict.move_to_end on
    successful access keeps recently-used at the tail).
    """

    DEFAULT_CAPACITY = 50

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._store: OrderedDict[str, Checkpoint] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def record(
        self,
        applied: dict[str, Any],
        snapshot: dict[str, str],
    ) -> str:
        """Record a successful apply; return checkpoint id."""
        ckpt = Checkpoint(applied, snapshot)
        with self._lock:
            self._store[ckpt.id] = ckpt
            self._evict_lru()
        return ckpt.id

    def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Look up a checkpoint by id (touches LRU recency)."""
        with self._lock:
            ckpt = self._store.get(checkpoint_id)
            if ckpt is not None:
                self._store.move_to_end(checkpoint_id)
            return ckpt

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
        """Drop a checkpoint by id (used by TransactionStore cascade evict)."""
        with self._lock:
            return self._store.pop(checkpoint_id, None) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def _evict_lru(self) -> None:
        """Caller holds self._lock."""
        while len(self._store) > self._capacity:
            self._store.popitem(last=False)
