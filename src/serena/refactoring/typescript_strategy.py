"""TypeScript refactoring strategy — Stream 6 / Leaf A.

Single-LSP strategy: vtsls (``@vtsls/language-server``) is the canonical
TypeScript LSP for cross-file rename, extract, inline, and import-organisation
operations.

Mirrors ``MarkdownStrategy`` (the simpler single-LSP reference):

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"vtsls": <SolidLanguageServer>}``;
  - ``execute_command_whitelist()`` classmethod returns frozenset() — vtsls
    exposes its refactor operations exclusively via code actions, not via
    ``workspace/executeCommand`` verbs (unlike pylsp-rope).

vtsls code action kinds (sourced from yioneko/vtsls README + LSP cap
introspection of ``VtslsServer._get_initialize_params``):

  ``source.organizeImports`` — remove unused imports, sort import order.
  ``source.fixAll``          — apply all auto-fixable diagnostics at once.
  ``refactor.extract``       — generic extract refactor family.
  ``refactor.extract.function``  — extract selection into a new function.
  ``refactor.extract.variable``  — extract expression into a new ``const``.
  ``refactor.extract.type``      — extract type alias.
  ``refactor.extract.constant``  — extract to module-level constant.
  ``refactor.inline``        — inline a local variable / function.
  ``refactor.inline.variable``   — inline a specific variable.
  ``refactor.move``          — move declarations between files.
  ``refactor.rewrite``       — rewrite (e.g. convert to arrow function).
  ``quickfix``               — quick-fix offered diagnostics.
  ``refactor``               — root parent kind (server may use for grouping).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the TypeScript/JavaScript extension allow-list.
# Mirrors the matcher in ``solidlsp.ls_config.Language.TYPESCRIPT
# .get_source_fn_matcher`` (*.ts, *.tsx, *.js, *.jsx, *.mts, *.cts,
# *.mjs, *.cjs); facades that want to enforce extension-level gates read
# from this constant rather than re-deriving.
_TYPESCRIPT_EXTENSIONS: frozenset[str] = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"}
)

# Code action kinds that vtsls advertises and that the o2-scalpel facades will
# dispatch. Sourced from VtslsServer._get_initialize_params codeActionKind
# valueSet (the client tells the server which kinds it understands; the server
# then only offers those). Kept as a frozenset to allow O(1) membership tests.
_TYPESCRIPT_CODE_ACTION_KINDS: frozenset[str] = frozenset(
    {
        "source.organizeImports",
        "source.fixAll",
        "refactor.extract",
        "refactor.extract.function",
        "refactor.extract.variable",
        "refactor.extract.type",
        "refactor.extract.constant",
        "refactor.inline",
        "refactor.inline.variable",
        "refactor.move",
        "refactor.rewrite",
        "quickfix",
        "refactor",
    }
)


class TypescriptStrategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for TypeScript/JavaScript (vtsls).

    The strategy is intentionally single-LSP — vtsls covers the complete
    refactor surface for TypeScript/JavaScript: rename, extract, inline,
    import-organisation, and quick-fixes. A potential secondary server (e.g.
    ``eslint-lsp`` for lint-only actions) could be added in a future leaf
    by extending ``build_servers`` to a two-entry dict, but that complexity
    is deferred until a concrete gap surfaces (YAGNI).
    """

    language_id: str = "typescript"
    extension_allow_list: frozenset[str] = _TYPESCRIPT_EXTENSIONS
    code_action_allow_list: frozenset[str] = _TYPESCRIPT_CODE_ACTION_KINDS

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"vtsls": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry. The pool's
        spawn function wraps the spawned server in ``_AsyncAdapter`` so that
        ``MultiServerCoordinator.broadcast`` can ``await`` the facade methods.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"vtsls": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        vtsls exposes its refactor surface exclusively through code actions
        (``textDocument/codeAction``), not via ``workspace/executeCommand``.
        The whitelist is therefore empty. If a future vtsls release adds
        execute-command verbs they land here — keeping the table next to the
        strategy preserves the single-source-of-truth invariant.
        """
        return frozenset()
