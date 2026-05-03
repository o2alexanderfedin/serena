"""v1.1 Stream 5 / Leaf 06 — pending-transaction schema + disk store.

Backs ``confirmation_mode='manual'`` for ``scalpel_dry_run_compose`` and the
new ``scalpel_confirm_annotations`` MCP tool. When the LLM opts into manual
review, ``DryRunComposeTool`` writes a ``PendingTransaction`` to disk
keyed by ``transaction_id``; ``scalpel_confirm_annotations`` reads it back,
filters the underlying ``WorkspaceEdit`` by accepted ``AnnotationGroup``
labels, and applies the filtered edit before discarding the pending entry.

Persistence shape mirrors :mod:`serena.refactoring.checkpoint_disk`:

* one JSON file per transaction id under ``root``;
* atomic write via ``write_text`` to a sibling tempfile + ``Path.replace``;
* corrupt/legacy files surface as ``None`` on read rather than raising —
  the next ``put`` overwrites them and the surrounding workflow treats the
  miss as ``UNKNOWN_TRANSACTION``.

The store is intentionally simpler than ``DiskCheckpointStore`` (no FIFO
eviction): pending tx are always discarded explicitly via
``scalpel_confirm_annotations``; the queue is bounded by the surrounding
LLM dialogue, not by the store. If a future leaf needs eviction we'll add
it then (YAGNI).

Cross-reference: ``docs/design/mvp/open-questions/q4-changeannotations-auto-accept.md``
§6.3 line 211 carries the v1.1 endorsement of optional manual review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class AnnotationGroup(BaseModel):
    """One LSP ``ChangeAnnotation`` projected for the manual-review surface.

    ``label`` is the user-facing annotation label (matches ``ChangeAnnotation.label``);
    ``needs_confirmation`` mirrors the LSP ``needsConfirmation`` flag (advisory at
    MVP per Q4 §7.1, load-bearing under ``confirmation_mode='manual'`` per
    Q4 §6.3 line 211); ``edit_ids`` enumerates the annotation IDs of every
    ``AnnotatedTextEdit`` belonging to this group.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    needs_confirmation: bool
    edit_ids: tuple[str, ...]


class PendingTransaction(BaseModel):
    """Durable projection of a manual-mode pending compose transaction.

    Stored under :class:`DiskPendingTxStore` while the LLM decides which
    annotation groups to accept. ``workspace_edit`` is the raw LSP
    ``WorkspaceEdit`` dict whose ``changeAnnotations`` produced the
    ``groups`` projection — kept verbatim so
    :class:`~serena.tools.scalpel_primitives.ConfirmAnnotationsTool`
    can build a filtered edit (only the accepted groups' edits) and apply it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    groups: tuple[AnnotationGroup, ...]
    workspace_edit: dict[str, Any] = {}

    def requires_confirmation(self) -> bool:
        """Return ``True`` iff any annotation group has ``needs_confirmation``."""
        return any(g.needs_confirmation for g in self.groups)


class DiskPendingTxStore:
    """JSON-file-per-transaction store for :class:`PendingTransaction`.

    Construction is cheap: ``mkdir(parents=True, exist_ok=True)`` only.
    ``put`` writes atomically (``.tmp`` sibling + ``Path.replace``); ``get``
    tolerates corrupt/legacy files by returning ``None``. ``discard`` is
    idempotent. No eviction policy: callers always discard explicitly via
    the confirm/abandon path.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, tx_id: str) -> Path:
        return self._root / f"{tx_id}.json"

    def put(self, tx: PendingTransaction) -> None:
        """Atomically write ``tx`` to disk under its ``tx.id``."""
        target = self._path(tx.id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(tx.model_dump_json(), encoding="utf-8")
        tmp.replace(target)

    def get(self, tx_id: str) -> PendingTransaction | None:
        """Read ``tx_id``; return ``None`` on miss or schema rejection."""
        path = self._path(tx_id)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            return PendingTransaction.model_validate_json(raw)
        except (ValidationError, ValueError, OSError):
            return None

    def has_pending(self, tx_id: str) -> bool:
        """True iff ``tx_id`` is on disk and decodes successfully."""
        return self.get(tx_id) is not None

    def discard(self, tx_id: str) -> bool:
        """Drop ``tx_id`` from disk. Idempotent — returns ``False`` on miss."""
        path = self._path(tx_id)
        if not path.is_file():
            return False
        path.unlink(missing_ok=True)
        return True


__all__ = [
    "AnnotationGroup",
    "DiskPendingTxStore",
    "PendingTransaction",
]
