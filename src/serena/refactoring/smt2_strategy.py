"""SMT-LIB 2 refactoring strategy — Stream 6 / Leaf F (v1.4.1: dolmenls).

Single-LSP strategy: ``dolmenls`` (Dolmen monorepo, https://github.com/Gbury/dolmen).

Mirrors ``LeanStrategy`` (the conservative single-LSP reference for Stream 6
Leaf E — another constraint/theorem domain with restricted refactor surface):

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"dolmenls": <SolidLanguageServer>}``;
  - ``execute_command_whitelist()`` classmethod returns ``frozenset()`` —
    dolmenls advertises no ``workspace/executeCommand`` verbs.

Why only ``quickfix``?
-----------------------
SMT-LIB 2 is a **constraint specification format**, not a general-purpose
programming language.  There is no notion of ``rename``/``extract`` at the
solver level:

  - Renaming a sort or function symbol across a multi-file benchmark suite
    requires solver-aware dependency tracking (e.g. shared axiom libraries,
    incremental check-sat sessions) that no current LSP provides.
  - Extracting a subformula into a named let-binding or define-fun may change
    the UNSAT-core produced by the solver, altering the semantics of the
    verification workflow.

``quickfix`` covers solver-reported diagnostic corrections (e.g. sort-mismatch
fixes, assertion syntax errors) — these are semantics-preserving.

This conservative allow-list is documented per DRY rule in
``Smt2Server._get_initialize_params`` (which also advertises only ``quickfix``
to the server, so the server never offers unsafe kinds).

SMT-LIB 2 code action kinds:

  ``quickfix``  — diagnostic-driven auto-corrections (sort mismatch, syntax).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the SMT-LIB 2 extension allow-list.
_SMT2_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".smt2",   # canonical SMT-LIB v2 extension
        ".smt",    # legacy / shorthand extension (used by some solver suites)
    }
)

# Code action kinds that a future SMT2 LSP would advertise.
# Conservative by design — see module docstring.
_SMT2_CODE_ACTION_KINDS: frozenset[str] = frozenset(
    {
        # Diagnostic-driven auto-corrections.
        # No rename/extract — SMT-LIB has no safe solver-level rename semantics.
        "quickfix",
    }
)


class Smt2Strategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for SMT-LIB 2 (dolmenls-backed, v1.4.1).

    The code-action surface is intentionally minimal (``quickfix`` only).
    See module docstring for the full constraint-format rationale.
    """

    language_id: str = "smt2"
    extension_allow_list: frozenset[str] = _SMT2_EXTENSIONS
    code_action_allow_list: frozenset[str] = _SMT2_CODE_ACTION_KINDS

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"dolmenls": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"dolmenls": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        Dolmenls (v0.10) advertises no executeCommand verbs; whitelist is empty.
        """
        return frozenset()
