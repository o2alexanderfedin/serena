"""v1.1 Stream 5 / Leaf 02 — disk checkpoint store + pydantic schema.

Two task surfaces:

- Task 1 — ``PersistedCheckpoint`` schema (this file, top half).
- Task 2 — ``DiskCheckpointStore`` write/read/list/evict (bottom half).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from serena.refactoring.checkpoint_disk import DiskCheckpointStore
from serena.refactoring.checkpoint_schema import PersistedCheckpoint


# ---------------------------------------------------------------------------
# Task 1 — PersistedCheckpoint schema
# ---------------------------------------------------------------------------


def test_persisted_checkpoint_required_fields() -> None:
    p = PersistedCheckpoint(
        id="ckpt-1",
        schema_version=1,
        created_at_ns=1,
        inverse_edit={"changes": {}},
        file_versions={"file:///a.py": 0},
    )
    assert p.id == "ckpt-1"
    assert p.schema_version == 1
    assert p.created_at_ns == 1
    assert p.inverse_edit == {"changes": {}}
    assert p.file_versions == {"file:///a.py": 0}


def test_persisted_checkpoint_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        PersistedCheckpoint(
            id="x",
            schema_version=1,
            created_at_ns=1,
            inverse_edit={},
            file_versions={},
            junk="no",  # type: ignore[call-arg]
        )


def test_persisted_checkpoint_rejects_empty_id() -> None:
    with pytest.raises(ValidationError):
        PersistedCheckpoint(
            id="",
            schema_version=1,
            created_at_ns=1,
            inverse_edit={},
            file_versions={},
        )


def test_persisted_checkpoint_rejects_negative_created_at() -> None:
    with pytest.raises(ValidationError):
        PersistedCheckpoint(
            id="x",
            schema_version=1,
            created_at_ns=-1,
            inverse_edit={},
            file_versions={},
        )


def test_persisted_checkpoint_rejects_zero_schema_version() -> None:
    with pytest.raises(ValidationError):
        PersistedCheckpoint(
            id="x",
            schema_version=0,
            created_at_ns=0,
            inverse_edit={},
            file_versions={},
        )


def test_persisted_checkpoint_is_frozen() -> None:
    p = PersistedCheckpoint(
        id="x",
        schema_version=1,
        created_at_ns=0,
        inverse_edit={},
        file_versions={},
    )
    with pytest.raises(ValidationError):
        p.id = "y"  # type: ignore[misc]


def test_persisted_checkpoint_round_trips_via_json() -> None:
    p = PersistedCheckpoint(
        id="ckpt-rt",
        schema_version=1,
        created_at_ns=42,
        inverse_edit={"documentChanges": [{"kind": "create", "uri": "file:///x.py"}]},
        file_versions={"file:///x.py": 7},
    )
    raw = p.model_dump_json()
    p2 = PersistedCheckpoint.model_validate_json(raw)
    assert p2 == p


# ---------------------------------------------------------------------------
# Task 2 — DiskCheckpointStore
# ---------------------------------------------------------------------------


def _mk(id_: str, ts: int = 0) -> PersistedCheckpoint:
    return PersistedCheckpoint(
        id=id_,
        schema_version=1,
        created_at_ns=ts,
        inverse_edit={"documentChanges": []},
        file_versions={},
    )


def test_disk_store_round_trip(tmp_path: Path) -> None:
    s = DiskCheckpointStore(tmp_path)
    p = _mk("c1", ts=10)
    s.put(p)
    got = s.get("c1")
    assert got == p


def test_disk_store_returns_none_on_miss(tmp_path: Path) -> None:
    s = DiskCheckpointStore(tmp_path)
    assert s.get("nope") is None


def test_disk_store_creates_root_lazily(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "checkpoints"
    assert not nested.exists()
    s = DiskCheckpointStore(nested)
    s.put(_mk("c", ts=1))
    assert nested.is_dir()
    assert s.get("c") is not None


def test_disk_store_lists_ids(tmp_path: Path) -> None:
    s = DiskCheckpointStore(tmp_path)
    s.put(_mk("a", ts=1))
    s.put(_mk("b", ts=2))
    s.put(_mk("c", ts=3))
    assert s.list_ids() == ["a", "b", "c"]


def test_disk_store_evicts_oldest(tmp_path: Path) -> None:
    """FIFO-by-mtime eviction. Mtimes are pinned explicitly so the test is
    deterministic regardless of the host filesystem's mtime resolution
    (HFS+/APFS coarse-grain by default)."""
    s = DiskCheckpointStore(tmp_path, max_entries=2)
    s.put(_mk("c0", ts=10))
    os.utime(tmp_path / "c0.json", (1.0, 1.0))
    s.put(_mk("c1", ts=20))
    os.utime(tmp_path / "c1.json", (2.0, 2.0))
    # Adding a third with max=2 must evict c0 (the oldest).
    s.put(_mk("c2", ts=30))
    os.utime(tmp_path / "c2.json", (3.0, 3.0))
    # Trigger one more eviction sweep (no-op write — but mtime stable).
    s.put(_mk("c3", ts=40))
    os.utime(tmp_path / "c3.json", (4.0, 4.0))
    # c3's put-time eviction may have run before its own utime call, leaving
    # ordering ambiguous; force final sweep with max-respecting put.
    s.put(_mk("c3", ts=40))  # idempotent overwrite; runs sweep with stable mtimes
    assert s.get("c0") is None
    assert s.get("c1") is None  # second-oldest evicted
    assert s.get("c2") is not None
    assert s.get("c3") is not None


def test_disk_store_evict_id(tmp_path: Path) -> None:
    s = DiskCheckpointStore(tmp_path)
    s.put(_mk("a", ts=1))
    assert s.evict("a") is True
    assert s.get("a") is None
    # Idempotent.
    assert s.evict("a") is False


def test_disk_store_overwrites_same_id(tmp_path: Path) -> None:
    s = DiskCheckpointStore(tmp_path)
    s.put(_mk("a", ts=1))
    s.put(
        PersistedCheckpoint(
            id="a",
            schema_version=1,
            created_at_ns=99,
            inverse_edit={"documentChanges": [{"kind": "create", "uri": "file:///x"}]},
            file_versions={"file:///x": 1},
        )
    )
    got = s.get("a")
    assert got is not None
    assert got.created_at_ns == 99
    assert got.file_versions == {"file:///x": 1}


def test_disk_store_get_rejects_corrupt_file(tmp_path: Path) -> None:
    s = DiskCheckpointStore(tmp_path)
    (tmp_path / "bad.json").write_text("{not json")
    # Corrupt files surface as None (treat as miss); matches lazy-fetch tolerance.
    assert s.get("bad") is None


def test_disk_store_len(tmp_path: Path) -> None:
    s = DiskCheckpointStore(tmp_path)
    assert len(s) == 0
    s.put(_mk("a", ts=1))
    s.put(_mk("b", ts=2))
    assert len(s) == 2


def test_disk_store_rejects_bad_max_entries(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        DiskCheckpointStore(tmp_path, max_entries=0)
