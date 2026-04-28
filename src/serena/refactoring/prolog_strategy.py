"""Prolog refactoring strategy — Stream 6 / Leaf G.

Single-LSP strategy: ``swipl`` + ``lsp_server`` pack
(https://github.com/jamesnvc/lsp_server).

Mirrors the ``LeanStrategy`` shape for single-LSP languages (Stream 6 Leaf E)
but exposes a wider code-action surface because Prolog predicate renaming is
a clean alpha-substitution:

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"swipl-lsp": <SolidLanguageServer>}``;
  - ``execute_command_whitelist()`` classmethod returns ``frozenset()`` —
    the lsp_server pack exposes its refactor surface via code actions, not
    ``workspace/executeCommand`` verbs.

Why ``quickfix`` + ``refactor.rename`` (but no ``refactor.extract``)?
-----------------------------------------------------------------------
Prolog predicates are purely symbolic names — there are no dependent types
and no proof contexts.  Renaming ``foo/2`` to ``bar/2`` is a safe
alpha-substitution: every call site in the current file that matches the
arity is updated, and the meaning of the program is preserved.

The ``lsp_server`` pack implements ``textDocument/rename`` for both variables
(scoped within a clause) and atom/predicate renaming (scoped within the
current file).

``refactor.extract`` is excluded because extracting a goal into a separate
predicate requires understanding of the caller's binding context (which
variables are already bound, which are unbound outputs), and the current
lsp_server implementation does not provide this analysis.

Prolog code action kinds:

  ``quickfix``        — singleton-variable warnings, syntax errors, unused
                        imports.  Semantics-preserving by definition.

  ``refactor.rename`` — variable and predicate (atom) renaming within the
                        current file.  Safe alpha-substitution in Prolog.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the Prolog extension allow-list.
_PROLOG_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pl",      # canonical SWI-Prolog extension (also Perl — context disambiguates)
        ".pro",     # alternative Prolog extension used by SWI and others
        ".prolog",  # explicit Prolog extension (unambiguous)
    }
)

# Code action kinds that the lsp_server pack advertises and that the
# o2-scalpel facades will dispatch.  See module docstring for rationale.
_PROLOG_CODE_ACTION_KINDS: frozenset[str] = frozenset(
    {
        # Diagnostic quick-fixes: singleton variables, syntax errors, unused predicates.
        "quickfix",
        # Predicate and variable renaming — safe alpha-substitution in Prolog.
        "refactor.rename",
    }
)


class PrologStrategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for Prolog (``swipl`` + lsp_server pack).

    Exposes ``quickfix`` and ``refactor.rename`` — Prolog predicate renaming
    is a clean alpha-substitution (no dependent types, no proof context).
    ``refactor.extract`` is excluded because goal extraction requires
    binding-context analysis that the current pack does not provide.

    Install via SWI-Prolog pack manager:
      ``swipl -g "pack_install(lsp_server)" -t halt``

    Requires SWI-Prolog 8.1.5 or newer.
    """

    language_id: str = "prolog"
    extension_allow_list: frozenset[str] = _PROLOG_EXTENSIONS
    code_action_allow_list: frozenset[str] = _PROLOG_CODE_ACTION_KINDS

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"swipl-lsp": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"swipl-lsp": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        The lsp_server pack exposes its refactor surface via code actions
        (``textDocument/codeAction``) and ``textDocument/rename``, not via
        ``workspace/executeCommand`` from the strategy layer.  The whitelist
        is therefore empty.
        """
        return frozenset()
