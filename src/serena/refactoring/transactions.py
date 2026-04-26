"""Transaction store + cascading checkpoint eviction (Stage 1B §4.1).

A ``Transaction`` aggregates N checkpoints recorded during a compose pipeline.
``TransactionStore.rollback(tid)`` walks members in REVERSE order and applies
each checkpoint's inverse through the caller-supplied applier_fn (typically
``LanguageServerCodeEditor._apply_workspace_edit``). Evicting a transaction
ALSO evicts its checkpoints from the bound ``CheckpointStore`` — keeps the
two stores' lifetimes coupled.

LRU(20) by insertion order; thread-safe via ``threading.Lock``.
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from .checkpoints import CheckpointStore


class Transaction:
    """One transaction = ordered list of checkpoint ids + replayable steps."""

    __slots__ = ("id", "checkpoint_ids", "steps", "expires_at")

    def __init__(self) -> None:
        self.id: str = uuid.uuid4().hex
        self.checkpoint_ids: list[str] = []
        self.steps: list[dict[str, Any]] = []
        self.expires_at: float = 0.0  # 0 = never expires; set by dry_run_compose


class TransactionStore:
    """In-memory LRU(20) of Transactions (§4.1 second store).

    ``checkpoint_store`` is the bound ``CheckpointStore``; eviction of a
    transaction cascade-evicts its checkpoints from that store.
    """

    DEFAULT_CAPACITY = 20

    def __init__(
        self,
        checkpoint_store: CheckpointStore,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        self._store: OrderedDict[str, Transaction] = OrderedDict()
        self._capacity = capacity
        self._checkpoints = checkpoint_store
        self._lock = threading.Lock()

    def begin(self) -> str:
        """Open a new transaction; return id."""
        txn = Transaction()
        # Phase 1: insert under our lock and harvest cascade victims.
        cascade_cids: list[str] = []
        with self._lock:
            self._store[txn.id] = txn
            cascade_cids = self._collect_evictions_locked()
        # Phase 2: evict cascade victims from CheckpointStore *outside* our
        # lock to avoid lock-order inversion (CheckpointStore has its own).
        for cid in cascade_cids:
            self._checkpoints.evict(cid)
        return txn.id

    def add_checkpoint(self, transaction_id: str, checkpoint_id: str) -> None:
        """Append a checkpoint to a transaction's member list.

        :raises KeyError: if transaction_id is unknown (or already evicted).
        """
        with self._lock:
            txn = self._store.get(transaction_id)
            if txn is None:
                raise KeyError(f"Unknown transaction id: {transaction_id}")
            txn.checkpoint_ids.append(checkpoint_id)
            self._store.move_to_end(transaction_id)

    def member_ids(self, transaction_id: str) -> list[str]:
        """Snapshot of member checkpoint ids in insertion order."""
        with self._lock:
            txn = self._store.get(transaction_id)
            if txn is None:
                return []
            return list(txn.checkpoint_ids)

    # --- Stage 2A additions: replayable steps + preview expiry ---

    def add_step(self, transaction_id: str, step: dict[str, Any]) -> None:
        """Append a {tool, args} step (Stage 2A — replayable from commit)."""
        with self._lock:
            txn = self._store.get(transaction_id)
            if txn is None:
                raise KeyError(f"Unknown transaction id: {transaction_id}")
            txn.steps.append(dict(step))
            self._store.move_to_end(transaction_id)

    def steps(self, transaction_id: str) -> list[dict[str, Any]]:
        """Snapshot of {tool, args} steps in insertion order."""
        with self._lock:
            txn = self._store.get(transaction_id)
            if txn is None:
                return []
            return [dict(s) for s in txn.steps]

    def set_expires_at(self, transaction_id: str, expires_at: float) -> None:
        """Set the absolute-epoch expiry timestamp (Stage 2A — commit checks)."""
        with self._lock:
            txn = self._store.get(transaction_id)
            if txn is None:
                raise KeyError(f"Unknown transaction id: {transaction_id}")
            txn.expires_at = float(expires_at)

    def expires_at(self, transaction_id: str) -> float:
        """Return the absolute-epoch expiry timestamp (0.0 means never)."""
        with self._lock:
            txn = self._store.get(transaction_id)
            if txn is None:
                return 0.0
            return float(txn.expires_at)

    def rollback(
        self,
        transaction_id: str,
        applier_fn: Callable[[dict[str, Any]], int],
    ) -> int:
        """Walk members in REVERSE order, invoking each checkpoint's restore.

        :param transaction_id: id returned by ``begin``. Unknown id → 0.
        :param applier_fn: typically ``LanguageServerCodeEditor._apply_workspace_edit``.
        :return: count of checkpoints whose restore returned True.
        """
        members = self.member_ids(transaction_id)
        if not members:
            return 0
        success = 0
        for cid in reversed(members):
            if self._checkpoints.restore(cid, applier_fn):
                success += 1
        return success

    def evict(self, transaction_id: str) -> bool:
        """Drop a transaction; cascade-evict its checkpoints."""
        with self._lock:
            txn = self._store.pop(transaction_id, None)
        if txn is None:
            return False
        # Cascade eviction outside our lock — CheckpointStore has its own.
        for cid in txn.checkpoint_ids:
            self._checkpoints.evict(cid)
        return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def _collect_evictions_locked(self) -> list[str]:
        """Caller holds self._lock. Pop over-capacity transactions and return
        the flat list of their checkpoint ids for cascade-evict OUTSIDE the
        lock (avoids lock-order inversion with CheckpointStore._lock).
        """
        cascade_cids: list[str] = []
        while len(self._store) > self._capacity:
            _evicted_id, evicted = self._store.popitem(last=False)
            cascade_cids.extend(evicted.checkpoint_ids)
        return cascade_cids
