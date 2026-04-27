"""v1.1 Stream 5 / Leaf 06 Task 1 — ``PendingTransaction`` schema tests.

Covers the pydantic model + the disk-backed pending-tx store that
``ScalpelRuntime.pending_tx_store()`` exposes for ``confirmation_mode='manual'``
(see ``06-scalpel-confirm-annotations.md`` Tasks 1-2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from serena.refactoring.pending_tx import (
    AnnotationGroup,
    DiskPendingTxStore,
    PendingTransaction,
)


# ---------------------------------------------------------------------------
# Task 1 — PendingTransaction schema
# ---------------------------------------------------------------------------


def test_pending_tx_with_two_annotation_groups() -> None:
    tx = PendingTransaction(
        id="tx-1",
        groups=(
            AnnotationGroup(label="rename", needs_confirmation=False, edit_ids=("e1",)),
            AnnotationGroup(label="extract", needs_confirmation=True, edit_ids=("e2", "e3")),
        ),
    )
    assert tx.requires_confirmation()


def test_pending_tx_without_confirmation_groups() -> None:
    tx = PendingTransaction(
        id="tx-2",
        groups=(
            AnnotationGroup(label="rename", needs_confirmation=False, edit_ids=("e1",)),
        ),
    )
    assert tx.requires_confirmation() is False


def test_pending_tx_is_frozen() -> None:
    tx = PendingTransaction(id="tx-3", groups=())
    with pytest.raises(ValidationError):
        tx.id = "mutated"  # type: ignore[misc]


def test_annotation_group_rejects_extra_fields() -> None:
    # ``extra="forbid"`` rejects unknown fields at validation time. Constructing
    # via ``**kwargs`` keeps pyright from flagging the missing parameter at the
    # call site — the failure is the runtime ValidationError this test asserts.
    bad: dict[str, object] = {
        "label": "rename",
        "needs_confirmation": True,
        "edit_ids": ("e1",),
        "extra": "nope",
    }
    with pytest.raises(ValidationError):
        AnnotationGroup(**bad)  # type: ignore[arg-type]


def test_pending_tx_round_trips_through_json() -> None:
    """JSON-roundtrip is what the disk store relies on."""
    tx = PendingTransaction(
        id="tx-4",
        groups=(
            AnnotationGroup(label="a", needs_confirmation=True, edit_ids=("e1", "e2")),
            AnnotationGroup(label="b", needs_confirmation=False, edit_ids=()),
        ),
        workspace_edit={"documentChanges": []},
    )
    raw = tx.model_dump_json()
    restored = PendingTransaction.model_validate_json(raw)
    assert restored == tx


# ---------------------------------------------------------------------------
# Task 1 — DiskPendingTxStore (disk persistence layer)
# ---------------------------------------------------------------------------


def _tx(id_: str) -> PendingTransaction:
    return PendingTransaction(
        id=id_,
        groups=(
            AnnotationGroup(label="rename", needs_confirmation=True, edit_ids=("e1",)),
        ),
        workspace_edit={"documentChanges": []},
    )


def test_disk_store_put_then_get_round_trips(tmp_path: Path) -> None:
    store = DiskPendingTxStore(root=tmp_path / "pending_tx")
    tx = _tx("tx-a")
    store.put(tx)
    assert store.get("tx-a") == tx


def test_disk_store_has_pending_tracks_membership(tmp_path: Path) -> None:
    store = DiskPendingTxStore(root=tmp_path / "pending_tx")
    assert store.has_pending("ghost") is False
    store.put(_tx("tx-b"))
    assert store.has_pending("tx-b") is True


def test_disk_store_discard_removes_entry(tmp_path: Path) -> None:
    store = DiskPendingTxStore(root=tmp_path / "pending_tx")
    store.put(_tx("tx-c"))
    assert store.discard("tx-c") is True
    assert store.has_pending("tx-c") is False
    assert store.discard("tx-c") is False  # idempotent


def test_disk_store_get_returns_none_for_missing(tmp_path: Path) -> None:
    store = DiskPendingTxStore(root=tmp_path / "pending_tx")
    assert store.get("ghost") is None


def test_disk_store_get_returns_none_for_corrupt_file(tmp_path: Path) -> None:
    """Corrupt JSON is treated as a miss (matches DiskCheckpointStore policy)."""
    root = tmp_path / "pending_tx"
    store = DiskPendingTxStore(root=root)
    (root / "bad.json").write_text("not valid json", encoding="utf-8")
    assert store.get("bad") is None
