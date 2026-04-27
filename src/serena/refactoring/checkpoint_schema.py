"""Pydantic schema for the v1.1 persistent disk checkpoint format.

This is the on-disk source of truth for ``DiskCheckpointStore``
(see ``checkpoint_disk.py``). The schema is intentionally minimal:

- ``schema_version`` lets future migrations evict/upgrade legacy entries.
- ``id`` mirrors the in-memory ``Checkpoint.id`` (uuid hex).
- ``created_at_ns`` records monotonic creation time (used by disk
  retention to evict the oldest entries when ``max_entries`` is exceeded).
- ``inverse_edit`` is the synthesised inverse ``WorkspaceEdit`` —
  the ONLY field consumed when ``CheckpointStore.restore`` re-applies a
  checkpoint loaded from disk.
- ``file_versions`` records per-URI document versions known at record
  time. Reserved for v1.2 stale-checkpoint detection (Leaf 06 will
  consume it). Empty dict is valid.

``ConfigDict(extra="forbid", frozen=True)``: unknown fields are rejected
on read (catches schema drift); instances are immutable so the disk
store can be treated as the source of truth without hidden mutations.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PersistedCheckpoint(BaseModel):
    """Disk-serialised projection of an in-memory ``Checkpoint``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    id: str = Field(min_length=1)
    created_at_ns: int = Field(ge=0)
    inverse_edit: dict[str, Any]
    file_versions: dict[str, int]
