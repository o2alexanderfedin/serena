"""Disk-backed pydantic checkpoint store (v1.1 Stream 5 / Leaf 02).

``DiskCheckpointStore`` is the durability layer behind the in-memory
``CheckpointStore`` LRU. One JSON file per checkpoint under ``root``,
schema validated by ``PersistedCheckpoint``.

Eviction policy: when ``max_entries`` is exceeded after a ``put``, drop
the oldest file by mtime (FIFO). The LRU recency layer in front sits in
``CheckpointStore`` so disk eviction is independent of access patterns.

Construction is cheap: ``mkdir(parents=True, exist_ok=True)`` only —
NO eager directory scan, NO eager load. ``CheckpointStore`` reads the
disk lazily, on LRU miss.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from .checkpoint_schema import PersistedCheckpoint


class DiskCheckpointStore:
    """Durable JSON-file-per-checkpoint store with FIFO eviction."""

    DEFAULT_MAX_ENTRIES = 200

    def __init__(self, root: Path, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be >= 1, got {max_entries}")
        self._root = Path(root)
        self._max = max_entries
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def max_entries(self) -> int:
        return self._max

    def _path(self, ckpt_id: str) -> Path:
        return self._root / f"{ckpt_id}.json"

    def put(self, ckpt: PersistedCheckpoint) -> None:
        """Write ``ckpt`` to disk; runs FIFO eviction if over budget.

        Same id overwrites the existing file (so ``Checkpoint`` re-record
        is idempotent on disk). The eviction sweep uses mtime which is
        refreshed by the write, so an overwrite cannot accidentally
        evict itself.
        """
        target = self._path(ckpt.id)
        # Atomic-ish write: write to a sibling tempfile and rename so a
        # crash mid-write cannot leave a half-written file readable.
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(ckpt.model_dump_json(), encoding="utf-8")
        tmp.replace(target)
        self._evict()

    def get(self, ckpt_id: str) -> PersistedCheckpoint | None:
        """Read ``ckpt_id``; return ``None`` on miss or schema-rejection.

        Corrupt/legacy files surface as ``None`` rather than raising —
        the caller treats them as a miss and the next ``put`` will
        eventually evict them via FIFO. This keeps the lazy-fetch path
        tolerant of partial writes from older serena versions.
        """
        path = self._path(ckpt_id)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return PersistedCheckpoint.model_validate_json(raw)
        except (ValidationError, ValueError, OSError):
            return None

    def list_ids(self) -> list[str]:
        """Return all known checkpoint ids on disk, sorted lexicographically."""
        return sorted(p.stem for p in self._root.glob("*.json"))

    def evict(self, ckpt_id: str) -> bool:
        """Drop a single checkpoint file by id. Idempotent."""
        path = self._path(ckpt_id)
        if not path.is_file():
            return False
        path.unlink(missing_ok=True)
        return True

    def __len__(self) -> int:
        return sum(1 for _ in self._root.glob("*.json"))

    def _evict(self) -> None:
        """FIFO eviction: drop oldest-by-mtime until <= ``max_entries``."""
        files = sorted(self._root.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(files) > self._max:
            oldest = files.pop(0)
            try:
                oldest.unlink(missing_ok=True)
            except OSError:  # pragma: no cover — best-effort
                break
