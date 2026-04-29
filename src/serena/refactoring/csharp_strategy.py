"""C# refactoring strategy — Stream 6 / Leaf I.

Single-LSP strategy: csharp-ls (https://github.com/razzmatazz/csharp-language-server)
is a Roslyn-based C# LSP server that supports cross-file rename, extract,
inline, rewrite, import-organisation, and quick-fix operations.

Mirrors ``JavaStrategy`` (the single-LSP reference for Stream 6 Leaf D):

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"csharp-ls": <SolidLanguageServer>}``;
  - ``execute_command_whitelist()`` classmethod returns frozenset() — csharp-ls
    exposes its refactor operations exclusively via code actions, not via
    ``workspace/executeCommand`` verbs from the strategy layer.

csharp-ls is simpler to install than OmniSharp (no tarball + Mono dance):
``dotnet tool install --global csharp-ls`` places the binary on PATH. It is
Roslyn-based and supports:

  ``quickfix``                        — quick-fix offered diagnostics.
  ``source.organizeImports``          — remove unused usings and sort.
  ``refactor.extract.method``         — extract selection to a new method.
  ``refactor.extract.variable``       — extract expression to a local variable.
  ``refactor.inline.method``          — inline a method at all call sites.
  ``refactor.rewrite``                — rewrite (convert, invert, etc.).
  ``refactor``                        — root parent kind (server may use for grouping).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the C# extension allow-list.
# csharp-ls handles all standard C# source file types.
_CSHARP_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Standard C# source
        ".cs",
        # C# script (Rosetta / dotnet-script)
        ".csx",
    }
)

# Code action kinds that csharp-ls advertises and that the o2-scalpel facades
# will dispatch. Sourced from CsharpLsServer._get_initialize_params
# codeActionKind valueSet (the client tells the server which kinds it
# understands; the server then only offers those). Kept as a frozenset to
# allow O(1) membership tests.
_CSHARP_CODE_ACTION_KINDS: frozenset[str] = frozenset(
    {
        # quick-fix offered diagnostics
        "quickfix",
        # import management
        "source.organizeImports",
        # extract refactors
        "refactor.extract",
        "refactor.extract.method",
        "refactor.extract.variable",
        # inline refactors
        "refactor.inline",
        "refactor.inline.method",
        # rewrite refactors
        "refactor.rewrite",
        # generic refactor parent kind
        "refactor",
    }
)


class CsharpStrategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for C# (csharp-ls).

    The strategy is intentionally single-LSP — csharp-ls covers the complete
    refactor surface for C#: rename, extract, inline, rewrite, import-
    organisation, and quick-fixes. csharp-ls is a Roslyn-based language server
    at https://github.com/razzmatazz/csharp-language-server.
    """

    language_id: str = "csharp"
    extension_allow_list: frozenset[str] = _CSHARP_EXTENSIONS
    code_action_allow_list: frozenset[str] = _CSHARP_CODE_ACTION_KINDS

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"csharp-ls": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry. The pool's
        spawn function wraps the spawned server in ``_AsyncAdapter`` so that
        ``MultiServerCoordinator.broadcast`` can ``await`` the facade methods.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"csharp-ls": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        csharp-ls exposes its refactor surface exclusively through code actions
        (``textDocument/codeAction``), not via ``workspace/executeCommand``
        from the strategy layer. The whitelist is therefore empty. If a
        future csharp-ls release adds execute-command verbs they land here —
        keeping the table next to the strategy preserves the single-source-
        of-truth invariant.
        """
        return frozenset()
