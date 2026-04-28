"""Markdown refactoring strategy — v1.1.1 Leaf 01.

Single-LSP strategy: marksman is the canonical markdown LSP for cross-file
heading + wiki-link awareness, so there is no multi-server merge here
(unlike ``PythonStrategy``'s pylsp-rope + basedpyright + ruff trio).

Mirrors ``RustStrategy`` (the simpler of the two reference strategies):

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"marksman": <_AsyncAdapter>}``;
  - ``execute_command_whitelist()`` classmethod returns frozenset()
    (marksman exposes no workspace/executeCommand verbs as of
    2026-02-08).

The four heading/wiki-link facades arrive in Leaf 02; this strategy is
the seam they will dispatch through.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the markdown extension allow-list. Mirrors the
# matcher in ``solidlsp.ls_config.Language.MARKDOWN.get_source_fn_matcher``
# (``*.md``, ``*.markdown``, ``*.mdx``); facades that want to enforce
# extension-level gates read from this constant rather than re-deriving.
_MARKDOWN_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown", ".mdx"})


class MarkdownStrategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for markdown (marksman).

    Stage 1H (when it lands for markdown) may grow ``code_action_allow_list``
    if marksman starts exposing code actions. Today (marksman 2026-02-08)
    the allow-list is intentionally empty — the four Leaf 02 facades use
    ``rename`` / ``documentSymbol`` / ``documentLink`` exclusively.
    """

    language_id: str = "markdown"
    extension_allow_list: frozenset[str] = _MARKDOWN_EXTENSIONS

    # marksman exposes no code actions today; future entries land alongside
    # whatever marksman release adds them so the facade surface stays stable.
    code_action_allow_list: frozenset[str] = frozenset()

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"marksman": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry. The pool's
        spawn function (``serena.tools.scalpel_runtime._default_spawn_fn``)
        is responsible for wrapping the spawned server in ``_AsyncAdapter``
        so that ``MultiServerCoordinator.broadcast`` can ``await`` the
        facade methods. (The spawn-dispatch wiring extension lands in
        Leaf 02 alongside the facades that consume it.)
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"marksman": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        marksman 2026-02-08 exposes no such verbs, so the whitelist is empty.
        Future verbs land here as marksman adds them — keeping the table
        next to the strategy preserves the single-source-of-truth invariant
        (per CLAUDE.md).
        """
        return frozenset()
