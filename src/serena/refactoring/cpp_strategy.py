"""C/C++ refactoring strategy — Stream 6 / Leaf C.

Single-LSP strategy: clangd (https://clangd.llvm.org) is the canonical
C/C++ LSP for cross-file rename, extract, inline, and include-organisation
operations.

Mirrors ``GolangStrategy`` (the single-LSP reference for Stream 6 Leaf B):

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"clangd": <SolidLanguageServer>}``;
  - ``execute_command_whitelist()`` classmethod returns frozenset() — clangd
    exposes its refactor operations exclusively via code actions, not via
    ``workspace/executeCommand`` verbs.

The unified ``language_id="cpp"`` covers both C and C++ source files.
clangd is a single LSP that handles all C-family languages — it determines
C vs. C++ mode from the file extension and compile flags in the project's
``compile_commands.json`` database, not from a separate protocol configuration.

clangd code action kinds (sourced from https://clangd.llvm.org/extensions
and LSP cap introspection of ``ClangdServer._get_initialize_params``):

  ``source.organizeImports``    — sort / deduplicate #include directives.
  ``source.fixAll.clangd``      — apply all auto-fixable diagnostics.
  ``refactor.extract``          — generic extract refactor family.
  ``refactor.extract.function`` — extract selection into a new function.
  ``refactor.inline``           — inline a function at all call sites.
  ``quickfix``                  — quick-fix offered diagnostics.
  ``refactor``                  — root parent kind (server may use for grouping).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the C/C++ extension allow-list.
# clangd handles all C-family file types through the same server instance.
# The list follows the LLVM/clangd documentation + common build-system conventions.
_CPP_EXTENSIONS: frozenset[str] = frozenset(
    {
        # C source
        ".c",
        # C++ source
        ".cc",
        ".cpp",
        ".cxx",
        ".c++",
        # C and C++ headers
        ".h",
        ".hh",
        ".hpp",
        ".hxx",
        ".h++",
        # Template implementations
        ".ipp",
        ".inl",
        ".tpp",
    }
)

# Code action kinds that clangd advertises and that the o2-scalpel facades will
# dispatch. Sourced from ClangdServer._get_initialize_params codeActionKind
# valueSet (the client tells the server which kinds it understands; the server
# then only offers those). Kept as a frozenset to allow O(1) membership tests.
_CPP_CODE_ACTION_KINDS: frozenset[str] = frozenset(
    {
        "source.organizeImports",
        "source.fixAll.clangd",
        "refactor.extract",
        "refactor.extract.function",
        "refactor.inline",
        "quickfix",
        "refactor",
    }
)


class CppStrategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for C/C++ (clangd).

    The strategy is intentionally single-LSP — clangd covers the complete
    refactor surface for C and C++: rename, extract, inline, include-organisation,
    and quick-fixes. clangd is the official C/C++ language server maintained
    by the LLVM project at https://clangd.llvm.org.
    """

    language_id: str = "cpp"
    extension_allow_list: frozenset[str] = _CPP_EXTENSIONS
    code_action_allow_list: frozenset[str] = _CPP_CODE_ACTION_KINDS

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"clangd": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry. The pool's
        spawn function wraps the spawned server in ``_AsyncAdapter`` so that
        ``MultiServerCoordinator.broadcast`` can ``await`` the facade methods.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"clangd": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        clangd exposes its refactor surface exclusively through code actions
        (``textDocument/codeAction``), not via ``workspace/executeCommand``.
        The whitelist is therefore empty. If a future clangd release adds
        execute-command verbs they land here — keeping the table next to the
        strategy preserves the single-source-of-truth invariant.
        """
        return frozenset()
