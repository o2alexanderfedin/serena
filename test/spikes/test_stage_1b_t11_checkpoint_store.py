"""T11 — CheckpointStore LRU(50) + restore behaviour."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from serena.refactoring.checkpoints import CheckpointStore


def _dummy_edit(uri: str = "file:///tmp/x") -> dict[str, Any]:
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


def test_record_returns_unique_ids() -> None:
    s = CheckpointStore()
    a = s.record(_dummy_edit("file:///tmp/a"), {"file:///tmp/a": "orig"})
    b = s.record(_dummy_edit("file:///tmp/b"), {"file:///tmp/b": "orig"})
    assert a != b
    assert len(s) == 2


def test_lru_eviction_at_capacity() -> None:
    s = CheckpointStore(capacity=3)
    ids = [s.record(_dummy_edit(f"file:///tmp/{i}"), {f"file:///tmp/{i}": "z"}) for i in range(5)]
    # Only the last 3 should remain.
    assert len(s) == 3
    assert s.get(ids[0]) is None
    assert s.get(ids[1]) is None
    assert s.get(ids[4]) is not None


def test_get_promotes_recency() -> None:
    s = CheckpointStore(capacity=3)
    a = s.record(_dummy_edit("file:///tmp/a"), {"file:///tmp/a": "z"})
    b = s.record(_dummy_edit("file:///tmp/b"), {"file:///tmp/b": "z"})
    c = s.record(_dummy_edit("file:///tmp/c"), {"file:///tmp/c": "z"})
    s.get(a)  # promote a → tail
    d = s.record(_dummy_edit("file:///tmp/d"), {"file:///tmp/d": "z"})
    # b should evict (was LRU after a's promotion); a/c/d remain.
    assert s.get(a) is not None
    assert s.get(b) is None
    assert s.get(c) is not None
    assert s.get(d) is not None


def test_restore_invokes_applier_with_inverse() -> None:
    s = CheckpointStore()
    edit = _dummy_edit("file:///tmp/r")
    cid = s.record(edit, {"file:///tmp/r": "OLD"})
    received: list[dict[str, Any]] = []
    def applier(e: dict[str, Any]) -> int:
        received.append(e)
        return 1
    ok = s.restore(cid, applier)
    assert ok is True
    assert len(received) == 1
    # T10 inverse for a TextDocumentEdit is a 3-op sequence:
    # [DeleteFile, CreateFile(overwrite=True), TextDocumentEdit insert].
    # The TextDocumentEdit re-installing the original content sits at index 2.
    chs = received[0]["documentChanges"]
    assert len(chs) == 3
    assert chs[0]["kind"] == "delete"
    assert chs[1]["kind"] == "create"
    assert chs[2]["edits"][0]["newText"] == "OLD"


def test_restore_unknown_id_returns_false() -> None:
    s = CheckpointStore()
    assert s.restore("ghost", lambda _e: 0) is False


def test_evict_drops_entry() -> None:
    s = CheckpointStore()
    cid = s.record(_dummy_edit(), {"file:///tmp/x": "z"})
    assert s.evict(cid) is True
    assert s.get(cid) is None
    assert s.evict(cid) is False  # idempotent


def test_concurrent_record_and_get(benchmark=None) -> None:  # noqa: ARG001
    """Smoke: 8 threads × 200 records each + interleaved gets — no exceptions."""
    s = CheckpointStore(capacity=2000)
    errors: list[BaseException] = []
    def worker(start: int) -> None:
        try:
            for i in range(200):
                cid = s.record(_dummy_edit(f"file:///tmp/{start}-{i}"), {f"file:///tmp/{start}-{i}": "z"})
                s.get(cid)
        except BaseException as e:
            errors.append(e)
    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # 8 × 200 = 1600 entries within capacity 2000.
    assert len(s) == 1600
