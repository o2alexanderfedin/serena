"""PC2 coverage uplift — serena.refactoring.transactions uncovered ranges.

Target line ranges from Phase B coverage analysis:
  L66    begin() cascade eviction
  L77    add_checkpoint raises on unknown txn
  L83-87 add_checkpoint body
  L96    add_step raises on unknown txn
  L105   steps() on unknown txn
  L113   set_expires_at raises on unknown txn
  L121   expires_at() on unknown txn
  L135-142 rollback() with reverse-order restoration
  L146-149 evict() body (cascade)
  L151-153 evict() checkpoint cascade
  L156-157 __len__
  L166-167 _collect_evictions_locked triggers LRU drop + cascade

Pure unit tests — no LSP processes needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.refactoring.transactions import Transaction, TransactionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store_pair(capacity: int = 20) -> tuple[CheckpointStore, TransactionStore]:
    """Fresh CheckpointStore + TransactionStore pair for each test."""
    cs = CheckpointStore(capacity=50, disk_root=None)
    ts = TransactionStore(checkpoint_store=cs, capacity=capacity)
    return cs, ts


def _noop_applier(edit: dict[str, Any]) -> int:
    """Applier that reports 1 successful operation, does nothing."""
    return 1


def _zero_applier(edit: dict[str, Any]) -> int:
    """Applier that reports 0 operations (nothing applied)."""
    return 0


def _make_checkpoint(cs: CheckpointStore) -> str:
    """Record a dummy checkpoint; return its id."""
    return cs.record(
        applied={"documentChanges": []},
        snapshot={},
    )


# ---------------------------------------------------------------------------
# Transaction dataclass
# ---------------------------------------------------------------------------


class TestTransactionDataclass:
    def test_default_values(self) -> None:
        txn = Transaction()
        assert txn.id != ""
        assert txn.checkpoint_ids == []
        assert txn.steps == []
        assert txn.expires_at == 0.0

    def test_unique_ids(self) -> None:
        t1 = Transaction()
        t2 = Transaction()
        assert t1.id != t2.id


# ---------------------------------------------------------------------------
# TransactionStore.begin / add_checkpoint
# ---------------------------------------------------------------------------


class TestTransactionStoreBegin:
    def test_begin_returns_nonempty_id(self) -> None:
        _, ts = _store_pair()
        tid = ts.begin()
        assert len(tid) > 0

    def test_begin_increments_len(self) -> None:
        _, ts = _store_pair()
        assert len(ts) == 0
        ts.begin()
        assert len(ts) == 1
        ts.begin()
        assert len(ts) == 2

    def test_add_checkpoint_appends_to_member_list(self) -> None:
        cs, ts = _store_pair()
        tid = ts.begin()
        cid = _make_checkpoint(cs)
        ts.add_checkpoint(tid, cid)
        assert ts.member_ids(tid) == [cid]

    def test_add_checkpoint_unknown_txn_raises(self) -> None:
        _, ts = _store_pair()
        with pytest.raises(KeyError, match="Unknown transaction"):
            ts.add_checkpoint("nonexistent-id", "any-checkpoint")

    def test_member_ids_unknown_txn_returns_empty(self) -> None:
        _, ts = _store_pair()
        assert ts.member_ids("nonexistent") == []

    def test_multiple_checkpoints_in_order(self) -> None:
        cs, ts = _store_pair()
        tid = ts.begin()
        cid1 = _make_checkpoint(cs)
        cid2 = _make_checkpoint(cs)
        ts.add_checkpoint(tid, cid1)
        ts.add_checkpoint(tid, cid2)
        assert ts.member_ids(tid) == [cid1, cid2]


# ---------------------------------------------------------------------------
# TransactionStore.add_step / steps / set_expires_at / expires_at
# ---------------------------------------------------------------------------


class TestTransactionStoreSteps:
    def test_add_step_stores_step(self) -> None:
        _, ts = _store_pair()
        tid = ts.begin()
        ts.add_step(tid, {"tool": "scalpel_rename", "args": {"name": "foo"}})
        result = ts.steps(tid)
        assert len(result) == 1
        assert result[0]["tool"] == "scalpel_rename"

    def test_add_step_unknown_txn_raises(self) -> None:
        _, ts = _store_pair()
        with pytest.raises(KeyError, match="Unknown transaction"):
            ts.add_step("nonexistent-id", {"tool": "x"})

    def test_steps_unknown_txn_returns_empty(self) -> None:
        _, ts = _store_pair()
        assert ts.steps("nonexistent") == []

    def test_steps_returns_defensive_copies(self) -> None:
        _, ts = _store_pair()
        tid = ts.begin()
        ts.add_step(tid, {"tool": "t"})
        snap1 = ts.steps(tid)
        snap1[0]["tool"] = "mutated"
        snap2 = ts.steps(tid)
        assert snap2[0]["tool"] == "t"  # original unaffected

    def test_set_expires_at_stored(self) -> None:
        _, ts = _store_pair()
        tid = ts.begin()
        ts.set_expires_at(tid, 1234567890.0)
        assert ts.expires_at(tid) == 1234567890.0

    def test_set_expires_at_unknown_txn_raises(self) -> None:
        _, ts = _store_pair()
        with pytest.raises(KeyError, match="Unknown transaction"):
            ts.set_expires_at("nonexistent", 0.0)

    def test_expires_at_unknown_txn_returns_zero(self) -> None:
        _, ts = _store_pair()
        assert ts.expires_at("nonexistent") == 0.0


# ---------------------------------------------------------------------------
# TransactionStore.rollback
# ---------------------------------------------------------------------------


class TestTransactionStoreRollback:
    def test_rollback_unknown_txn_returns_zero(self) -> None:
        _, ts = _store_pair()
        assert ts.rollback("nonexistent", _noop_applier) == 0

    def test_rollback_empty_txn_returns_zero(self) -> None:
        _, ts = _store_pair()
        tid = ts.begin()
        assert ts.rollback(tid, _noop_applier) == 0

    def test_rollback_restores_checkpoints_in_reverse(self) -> None:
        cs, ts = _store_pair()
        tid = ts.begin()

        restored_order: list[str] = []

        def _tracking_applier(edit: dict[str, Any]) -> int:
            # Capture which checkpoint we're restoring by inspecting the edit.
            restored_order.append(str(edit))
            return 1

        # Record two checkpoints with distinct edits.
        cid1 = cs.record(
            applied={"documentChanges": [{"textDocument": {"uri": "file:///a.py"}, "edits": []}]},
            snapshot={"file:///a.py": "original_a"},
        )
        cid2 = cs.record(
            applied={"documentChanges": [{"textDocument": {"uri": "file:///b.py"}, "edits": []}]},
            snapshot={"file:///b.py": "original_b"},
        )
        ts.add_checkpoint(tid, cid1)
        ts.add_checkpoint(tid, cid2)

        count = ts.rollback(tid, _tracking_applier)
        assert count == 2
        # Reverse order: cid2 restored first, cid1 second.
        assert len(restored_order) == 2
        # cid2's inverse should mention file b, cid1's inverse should mention file a.
        assert "file:///b.py" in restored_order[0]
        assert "file:///a.py" in restored_order[1]

    def test_rollback_partial_success_counted(self) -> None:
        cs, ts = _store_pair()
        tid = ts.begin()

        call_count = [0]

        def _sometimes_fail(edit: dict[str, Any]) -> int:
            call_count[0] += 1
            return 1 if call_count[0] % 2 == 0 else 0

        cid1 = _make_checkpoint(cs)
        cid2 = _make_checkpoint(cs)
        ts.add_checkpoint(tid, cid1)
        ts.add_checkpoint(tid, cid2)
        # One succeeds (count=0 after second call), one fails (count=0 after first).
        # _sometimes_fail: first call count=1 → 0; second call count=2 → 1.
        count = ts.rollback(tid, _sometimes_fail)
        assert count == 1  # exactly one succeeded


# ---------------------------------------------------------------------------
# TransactionStore.evict
# ---------------------------------------------------------------------------


class TestTransactionStoreEvict:
    def test_evict_existing_txn_returns_true(self) -> None:
        _, ts = _store_pair()
        tid = ts.begin()
        assert ts.evict(tid) is True
        assert len(ts) == 0

    def test_evict_unknown_txn_returns_false(self) -> None:
        _, ts = _store_pair()
        assert ts.evict("nonexistent") is False

    def test_evict_cascade_removes_checkpoints(self) -> None:
        cs, ts = _store_pair()
        tid = ts.begin()
        cid = _make_checkpoint(cs)
        ts.add_checkpoint(tid, cid)
        assert cs.get(cid) is not None

        ts.evict(tid)
        # After cascade eviction the checkpoint should be gone.
        assert cs.get(cid) is None

    def test_evict_does_not_affect_other_txns(self) -> None:
        _, ts = _store_pair()
        tid1 = ts.begin()
        tid2 = ts.begin()
        ts.evict(tid1)
        assert len(ts) == 1
        assert ts.member_ids(tid2) == []


# ---------------------------------------------------------------------------
# TransactionStore LRU capacity eviction + cascade
# ---------------------------------------------------------------------------


class TestTransactionStoreLruEviction:
    def test_capacity_evicts_oldest_on_begin(self) -> None:
        cs, ts = _store_pair(capacity=3)
        tids = [ts.begin() for _ in range(4)]
        # After inserting 4 into capacity-3 store, size is 3.
        assert len(ts) == 3
        # The oldest (tids[0]) was evicted.
        assert ts.member_ids(tids[0]) == []

    def test_cascade_evict_removes_checkpoints(self) -> None:
        cs, ts = _store_pair(capacity=2)
        tid = ts.begin()
        cid = _make_checkpoint(cs)
        ts.add_checkpoint(tid, cid)
        # Insert 2 more to push tid out.
        ts.begin()
        ts.begin()
        # tid evicted; cascade should have dropped the checkpoint.
        assert cs.get(cid) is None

    def test_len_after_multiple_begins(self) -> None:
        _, ts = _store_pair(capacity=5)
        for _ in range(5):
            ts.begin()
        assert len(ts) == 5

    def test_len_after_evict(self) -> None:
        _, ts = _store_pair()
        tid = ts.begin()
        assert len(ts) == 1
        ts.evict(tid)
        assert len(ts) == 0
