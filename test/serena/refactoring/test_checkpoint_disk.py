"""v1.1 Stream 5 / Leaf 02 — disk checkpoint store + pydantic schema.

Two task surfaces:

- Task 1 — ``PersistedCheckpoint`` schema (this file, top half).
- Task 2 — ``DiskCheckpointStore`` write/read/list/evict (bottom half).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
