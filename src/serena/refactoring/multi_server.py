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


# ---------------------------------------------------------------------------
# Imports needed for runtime behaviors below.
# ---------------------------------------------------------------------------

import asyncio
import os
import time

# Methods broadcast() can dispatch. Each entry maps an LSP wire method
# name to the SolidLanguageServer facade name that implements it.
# ``textDocument/rename`` is intentionally NOT broadcast — it goes
# through ``merge_rename()`` (T8) which is single-primary per §11.3.
_BROADCAST_DISPATCH: dict[str, str] = {
    "textDocument/codeAction": "request_code_actions",
    "codeAction/resolve": "resolve_code_action",
    "workspace/executeCommand": "execute_command",
}


def _default_broadcast_timeout_ms() -> int:
    """Per-call default; ``O2_SCALPEL_BROADCAST_TIMEOUT_MS`` overrides."""
    raw = os.environ.get("O2_SCALPEL_BROADCAST_TIMEOUT_MS")
    if raw is None:
        return 2000
    try:
        v = int(raw)
        return v if v > 0 else 2000
    except ValueError:
        return 2000


# ---------------------------------------------------------------------------
# §11.1 + Phase 0 P2 — sub-kind normalization for priority-table lookup.
# ---------------------------------------------------------------------------

# Server-suffix tokens recognized by the merger. Stage 1E adapters
# may extend this set; per Phase 0 P2 only "ruff" appears in the wild
# at MVP, but defensive entries cover future expansions and the
# hierarchical-collision case noted in §11.2.
_KNOWN_SERVER_SUFFIXES: frozenset[str] = frozenset({
    "ruff",
    "pylsp-rope",
    "pylsp-base",
    "pylsp-mypy",
    "basedpyright",
    "rust-analyzer",
})

# Base families against which the §11.1 priority table is keyed.
# A hierarchical kind ``<family>.<server-suffix>`` collapses to
# ``<family>`` for priority-table lookup. Other hierarchies (e.g.
# ``refactor.extract.function``) are NOT collapsed — they're semantic
# sub-actions, not server tags.
_PRIORITY_BASE_FAMILIES: frozenset[str] = frozenset({
    "source.organizeImports",
    "source.fixAll",
    "quickfix",
    "refactor.extract",
    "refactor.inline",
    "refactor.rewrite",
    "refactor",
    "source",
})


def _normalize_kind(kind: str) -> str:
    """Collapse hierarchical server-suffix kinds onto their priority family.

    Per LSP §3.18.1, CodeActionKind values are dot-separated hierarchies
    (e.g. ``source.organizeImports.ruff``). Phase 0 P2 confirmed ruff
    publishes under such suffixes while pylsp-rope publishes the bare
    family. The §11.1 priority table is keyed by family, so the merger
    rewrites suffixed kinds before lookup.

    Rule: if ``kind`` decomposes into ``<family>.<server>`` where
    ``<family>`` is in ``_PRIORITY_BASE_FAMILIES`` and ``<server>`` is in
    ``_KNOWN_SERVER_SUFFIXES``, return ``<family>``. Otherwise return
    ``kind`` unchanged.

    Examples:
      ``source.organizeImports.ruff`` → ``source.organizeImports``
      ``source.fixAll.ruff`` → ``source.fixAll``
      ``refactor.extract.function`` → ``refactor.extract.function`` (kept)
      ``quickfix`` → ``quickfix`` (already a family)
    """
    if not kind or "." not in kind:
        return kind
    head, _, tail = kind.rpartition(".")
    if head in _PRIORITY_BASE_FAMILIES and tail in _KNOWN_SERVER_SUFFIXES:
        return head
    return kind


class MultiServerCoordinator:
    """Coordinator for the §11 multi-LSP merge.

    Holds a ``dict[server_id, server]`` pool. Servers are duck-typed:
    in production they are ``SolidLanguageServer`` subclasses (Stage 1E
    adapters). In Stage 1D unit tests they are ``_FakeServer`` doubles
    from ``test/spikes/conftest.py``. Method shapes are identical.
    """

    def __init__(self, servers: dict[str, Any]) -> None:
        self._servers = dict(servers)

    @property
    def servers(self) -> dict[str, Any]:
        return dict(self._servers)

    async def broadcast(
        self,
        method: str,
        kwargs: dict[str, Any],
        timeout_ms: int | None = None,
    ) -> MultiServerBroadcastResult:
        """Fan ``method`` with ``kwargs`` to every server in the pool.

        Returns a ``MultiServerBroadcastResult`` collecting:
          - ``responses``: ``{server_id: response}`` for servers that
            answered within ``timeout_ms``.
          - ``timeouts``: ``ServerTimeoutWarning`` per server that
            exceeded the deadline.
          - ``errors``: ``{server_id: stringified-exception}`` per
            server that raised.

        ``timeout_ms`` defaults to ``$O2_SCALPEL_BROADCAST_TIMEOUT_MS``
        or 2000ms per §11.2 row "Server times out (>2 s for codeAction)".
        """
        facade_name = _BROADCAST_DISPATCH.get(method)
        if facade_name is None:
            raise ValueError(f"unsupported broadcast method: {method!r}")
        deadline_ms = timeout_ms if timeout_ms is not None else _default_broadcast_timeout_ms()
        timeout_s = deadline_ms / 1000.0

        async def _one(server_id: str, server: Any) -> tuple[str, Any | BaseException, float]:
            facade = getattr(server, facade_name)
            t0 = time.monotonic()
            try:
                resp = await asyncio.wait_for(facade(**kwargs), timeout=timeout_s)
                return server_id, resp, (time.monotonic() - t0) * 1000.0
            except asyncio.TimeoutError as exc:
                return server_id, exc, (time.monotonic() - t0) * 1000.0
            except BaseException as exc:  # noqa: BLE001
                return server_id, exc, (time.monotonic() - t0) * 1000.0

        gathered = await asyncio.gather(
            *[_one(sid, srv) for sid, srv in self._servers.items()],
            return_exceptions=False,
        )
        out = MultiServerBroadcastResult()
        for sid, resp_or_exc, after_ms in gathered:
            if isinstance(resp_or_exc, asyncio.TimeoutError):
                out.timeouts.append(
                    ServerTimeoutWarning(
                        server=sid,
                        method=method,
                        timeout_ms=deadline_ms,
                        after_ms=int(after_ms),
                    )
                )
            elif isinstance(resp_or_exc, BaseException):
                out.errors[sid] = f"{type(resp_or_exc).__name__}: {resp_or_exc}"
            else:
                out.responses[sid] = resp_or_exc
        return out


__all__ = [
    "MergedCodeAction",
    "MultiServerBroadcastResult",
    "MultiServerCoordinator",
    "ProvenanceLiteral",
    "ServerTimeoutWarning",
    "SuppressedAlternative",
]
