"""T12 — TransactionStore LRU(20) + cascade-evict checkpoints + reverse rollback."""

from __future__ import annotations

from typing import Any

import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.refactoring.transactions import TransactionStore


def _dummy_edit(uri: str) -> dict[str, Any]:
    return {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                        "newText": "X",
                    }
                ],
            }
        ]
    }


def test_begin_and_add_checkpoint() -> None:
    cstore = CheckpointStore()
    tstore = TransactionStore(checkpoint_store=cstore)
    tid = tstore.begin()
    cid = cstore.record(_dummy_edit("file:///tmp/a"), {"file:///tmp/a": "z"})
    tstore.add_checkpoint(tid, cid)
    assert tstore.member_ids(tid) == [cid]


def test_rollback_walks_members_in_reverse() -> None:
    cstore = CheckpointStore()
    tstore = TransactionStore(checkpoint_store=cstore)
    tid = tstore.begin()
    cids = []
    for i in range(3):
        cid = cstore.record(_dummy_edit(f"file:///tmp/{i}"), {f"file:///tmp/{i}": str(i)})
        tstore.add_checkpoint(tid, cid)
        cids.append(cid)
    invocation_order: list[str] = []
    def applier(edit: dict[str, Any]) -> int:
        # Edit's first textDocument URI tells us which checkpoint fired.
        chs = edit["documentChanges"]
        # The inverse for a TextDocumentEdit is also a TextDocumentEdit; pick its uri.
        invocation_order.append(chs[0]["textDocument"]["uri"])
        return 1
    n = tstore.rollback(tid, applier)
    assert n == 3
    # Reverse member order: cids[2] then cids[1] then cids[0].
    assert invocation_order == ["file:///tmp/2", "file:///tmp/1", "file:///tmp/0"]


def test_lru_eviction_cascades_to_checkpoints() -> None:
    cstore = CheckpointStore(capacity=1000)
    tstore = TransactionStore(checkpoint_store=cstore, capacity=2)
    # Begin 3 transactions, each owns 2 checkpoints. T1 evicts when T3 begins.
    tids: list[str] = []
    cids_per_tid: dict[str, list[str]] = {}
    for t in range(3):
        tid = tstore.begin()
        tids.append(tid)
        cids_per_tid[tid] = []
        for i in range(2):
            cid = cstore.record(_dummy_edit(f"file:///tmp/{t}-{i}"), {f"file:///tmp/{t}-{i}": "z"})
            tstore.add_checkpoint(tid, cid)
            cids_per_tid[tid].append(cid)
    # T1 evicted: its checkpoints must be gone too.
    for cid in cids_per_tid[tids[0]]:
        assert cstore.get(cid) is None
    # T2 / T3 checkpoints survive.
    for tid in tids[1:]:
        for cid in cids_per_tid[tid]:
            assert cstore.get(cid) is not None


def test_rollback_unknown_id_returns_zero() -> None:
    tstore = TransactionStore(checkpoint_store=CheckpointStore())
    assert tstore.rollback("ghost", lambda _e: 1) == 0


def test_add_checkpoint_unknown_transaction_raises() -> None:
    cstore = CheckpointStore()
    tstore = TransactionStore(checkpoint_store=cstore)
    cid = cstore.record(_dummy_edit("file:///tmp/x"), {"file:///tmp/x": "z"})
    with pytest.raises(KeyError):
        tstore.add_checkpoint("ghost", cid)


def test_rollback_short_circuit_on_failed_restore() -> None:
    """If applier_fn returns 0 for one inverse, rollback continues to next."""
    cstore = CheckpointStore()
    tstore = TransactionStore(checkpoint_store=cstore)
    tid = tstore.begin()
    cid_a = cstore.record(_dummy_edit("file:///tmp/A"), {"file:///tmp/A": "a"})
    cid_b = cstore.record(_dummy_edit("file:///tmp/B"), {"file:///tmp/B": "b"})
    tstore.add_checkpoint(tid, cid_a)
    tstore.add_checkpoint(tid, cid_b)
    # Applier reports zero for B's inverse (e.g. file disappeared).
    def applier(edit: dict[str, Any]) -> int:
        uri = edit["documentChanges"][0]["textDocument"]["uri"]
        return 0 if "B" in uri else 1
    n = tstore.rollback(tid, applier)
    # Only A counted as successful; B counted as failed.
    assert n == 1
