"""Lean 4 refactoring strategy — Stream 6 / Leaf E.

Single-LSP strategy: ``lean --server`` (https://leanprover.github.io/lean4/)
is the built-in Lean 4 language server invoked over stdio.

Mirrors ``CppStrategy`` (the single-LSP reference for Stream 6 Leaf C):

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"lean": <SolidLanguageServer>}``;
  - ``execute_command_whitelist()`` classmethod returns ``frozenset()`` —
    ``lean --server`` exposes its suggestions exclusively via code actions,
    not via ``workspace/executeCommand`` verbs from the strategy layer.

Why only ``quickfix``?
-----------------------
Lean 4 is a **dependently-typed theorem prover**.  In dependent type theory,
a term's *type* can depend on *values*, which means:

  - Renaming a hypothesis ``h`` in a tactic proof block can break all
    subsequent ``exact h`` / ``apply h`` references — the proof is
    definitionally different after the rename.
  - Extracting a subterm from a proof context can invalidate the goal
    (the extracted term carries the local context it was extracted from;
    outside that context the types no longer unify).

These semantic hazards are qualitatively different from the rename/extract
story in, say, Java or Python, where a rename is a pure alpha-substitution.
In Lean 4 it is not safe to offer rename/extract without a proof-aware
rewriter that understands the elaborator's context.

``quickfix`` code actions are semantics-preserving: they are tactic
suggestions (``"Try this: simp [...]"``, ``"Try this: exact ⟨_, rfl⟩"``)
that the elaborator has *already verified* will close the goal. Accepting
them can never break the proof.

This conservative allow-list is documented per DRY rule in
``LeanServer._get_initialize_params`` (which also advertises only
``quickfix`` to the server, so the server never offers unsafe kinds).

Lean 4 code action kinds:

  ``quickfix``  — tactic suggestions and diagnostic quick-fixes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the Lean 4 extension allow-list.
_LEAN_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".lean",
    }
)

# Code action kinds that ``lean --server`` advertises and that the
# o2-scalpel facades will dispatch.  Conservative by design — see the
# module docstring for the full theorem-prover rationale.
_LEAN_CODE_ACTION_KINDS: frozenset[str] = frozenset(
    {
        # Tactic suggestions and diagnostic quick-fixes.
        # This is the only kind safe for a dependent-type theorem prover;
        # see module docstring for why rename/extract are excluded.
        "quickfix",
    }
)


class LeanStrategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for Lean 4 (``lean --server``).

    The strategy is intentionally single-LSP and its code-action surface is
    intentionally minimal (``quickfix`` only).  See module docstring for the
    full rationale on why rename/extract are excluded from the allow-list.

    The LSP server ships with the Lean 4 compiler itself — no separate
    binary download required. Install via elan:
    https://github.com/leanprover/elan
    """

    language_id: str = "lean"
    extension_allow_list: frozenset[str] = _LEAN_EXTENSIONS
    code_action_allow_list: frozenset[str] = _LEAN_CODE_ACTION_KINDS

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"lean": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry. The pool's
        spawn function wraps the spawned server in ``_AsyncAdapter`` so that
        ``MultiServerCoordinator.broadcast`` can ``await`` the facade methods.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"lean": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        ``lean --server`` exposes its refactor surface exclusively through
        code actions (``textDocument/codeAction``), not via
        ``workspace/executeCommand`` from the strategy layer. The whitelist
        is therefore empty.
        """
        return frozenset()
