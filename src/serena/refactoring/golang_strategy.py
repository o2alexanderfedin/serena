"""Go refactoring strategy — Stream 6 / Leaf B.

Single-LSP strategy: gopls (``golang.org/x/tools/gopls``) is the canonical
Go LSP for cross-file rename, extract, inline, and import-organisation
operations.

Mirrors ``TypescriptStrategy`` (the single-LSP reference for Stream 6):

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"gopls": <SolidLanguageServer>}``;
  - ``execute_command_whitelist()`` classmethod returns frozenset() — gopls
    exposes its refactor operations exclusively via code actions, not via
    ``workspace/executeCommand`` verbs.

gopls code action kinds (sourced from golang/tools gopls documentation +
LSP cap introspection of ``GoplsServer._get_initialize_params``):

  ``source.organizeImports`` — remove unused imports, sort import order.
  ``source.fixAll``          — apply all auto-fixable diagnostics at once.
  ``refactor.extract``       — generic extract refactor family.
  ``refactor.extract.function``  — extract selection into a new function.
  ``refactor.extract.variable``  — extract expression into a new variable.
  ``refactor.inline``        — inline a function at all call sites.
  ``refactor.rewrite``       — rewrite (e.g. fill struct, fill switch).
  ``quickfix``               — quick-fix offered diagnostics.
  ``refactor``               — root parent kind (server may use for grouping).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the Go extension allow-list.
# Go files use the ``.go`` extension exclusively; the test runner uses
# ``*_test.go`` files which share the same extension.
_GOLANG_EXTENSIONS: frozenset[str] = frozenset({".go"})

# Code action kinds that gopls advertises and that the o2-scalpel facades will
# dispatch. Sourced from GoplsServer._get_initialize_params codeActionKind
# valueSet (the client tells the server which kinds it understands; the server
# then only offers those). Kept as a frozenset to allow O(1) membership tests.
_GOLANG_CODE_ACTION_KINDS: frozenset[str] = frozenset(
    {
        "source.organizeImports",
        "source.fixAll",
        "refactor.extract",
        "refactor.extract.function",
        "refactor.extract.variable",
        "refactor.inline",
        "refactor.rewrite",
        "quickfix",
        "refactor",
    }
)


class GolangStrategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for Go (gopls).

    The strategy is intentionally single-LSP — gopls covers the complete
    refactor surface for Go: rename, extract, inline, import-organisation,
    and quick-fixes. gopls is the official Go language server maintained
    by the Go team at https://github.com/golang/tools/tree/master/gopls.
    """

    language_id: str = "go"
    extension_allow_list: frozenset[str] = _GOLANG_EXTENSIONS
    code_action_allow_list: frozenset[str] = _GOLANG_CODE_ACTION_KINDS

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"gopls": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry. The pool's
        spawn function wraps the spawned server in ``_AsyncAdapter`` so that
        ``MultiServerCoordinator.broadcast`` can ``await`` the facade methods.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"gopls": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        gopls exposes its refactor surface exclusively through code actions
        (``textDocument/codeAction``), not via ``workspace/executeCommand``.
        The whitelist is therefore empty. If a future gopls release adds
        execute-command verbs they land here — keeping the table next to the
        strategy preserves the single-source-of-truth invariant.
        """
        return frozenset()
