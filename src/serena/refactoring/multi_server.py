"""Multi-LSP coordination for Python (scope-report §11).

Only Python uses multi-LSP at MVP: pylsp + basedpyright + ruff.
pylsp-mypy is DROPPED at MVP (Phase 0 P5a / SUMMARY §6) — the merger
never receives a pylsp-mypy candidate, but the ``provenance`` Literal
keeps it for v1.1 schema compatibility.

This module is the only place that knows about server identities.
Below: ``LanguageServerCodeEditor._apply_workspace_edit`` sees a single
merged ``WorkspaceEdit`` per call (with provenance annotations).
Above: facades see merged ``MergedCodeAction`` lists with
``suppressed_alternatives`` populated only when ``O2_SCALPEL_DEBUG_MERGE=1``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# §11.6 schemas — verbatim per scope report.
# ---------------------------------------------------------------------------

ProvenanceLiteral = Literal[
    "pylsp-rope",
    "pylsp-base",
    "basedpyright",
    "ruff",
    "pylsp-mypy",
    "rust-analyzer",
]


class SuppressedAlternative(BaseModel):
    """An alternative dropped during the §11.1 two-stage merge.

    Only attached to ``MergedCodeAction.suppressed_alternatives`` when
    ``O2_SCALPEL_DEBUG_MERGE=1``.
    """

    title: str
    provenance: str
    reason: Literal["lower_priority", "duplicate_title", "duplicate_edit"]


class MergedCodeAction(BaseModel):
    """A code action that survived the §11.1 two-stage merge.

    Carries ``provenance`` so the LLM can audit which server produced
    the winner; carries ``suppressed_alternatives`` (debug-only) so a
    diff against the unmerged set is reconstructable.
    """

    id: str
    title: str
    kind: str
    disabled_reason: str | None
    is_preferred: bool
    provenance: ProvenanceLiteral
    suppressed_alternatives: list[SuppressedAlternative] = Field(default_factory=list)


class ServerTimeoutWarning(BaseModel):
    """Single-server timeout entry, surfaced by ``broadcast()``."""

    server: str
    method: str
    timeout_ms: int
    after_ms: int


class MultiServerBroadcastResult(BaseModel):
    """Result of fanning a request to N servers in parallel.

    Internal to ``MultiServerCoordinator``; facades never see this
    shape — they see ``list[MergedCodeAction]``.
    """

    responses: dict[str, Any] = Field(default_factory=dict)
    timeouts: list[ServerTimeoutWarning] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


__all__ = [
    "MergedCodeAction",
    "MultiServerBroadcastResult",
    "ProvenanceLiteral",
    "ServerTimeoutWarning",
    "SuppressedAlternative",
]
