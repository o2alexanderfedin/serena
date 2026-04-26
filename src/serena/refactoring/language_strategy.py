"""Per-language refactoring strategy plug-points (Stage 1E §14.1 file 11).

The ``LanguageStrategy`` Protocol is the seam between the language-agnostic
facade layer (``LanguageServerCodeEditor``, ``MultiServerCoordinator``,
``LspPool``) and the per-language plug-ins (``RustStrategy``,
``PythonStrategy``, future ``GoStrategy`` etc.). Each strategy declares:

  - ``language_id`` (matches ``Language`` enum value, e.g. ``"python"``).
  - ``extension_allow_list`` — the set of file suffixes this strategy
    will accept; facades reject other paths up-front.
  - ``code_action_allow_list`` — the set of LSP code-action kinds (or
    kind prefixes per LSP §3.18.1) this strategy considers in-scope.
    Other kinds are filtered before the multi-server merge sees them.
  - ``build_servers(project_root)`` — returns the
    ``dict[server_id, SolidLanguageServer]`` that ``MultiServerCoordinator``
    will broadcast across. Single-LSP languages return a single-entry
    dict; Python returns a three-entry dict.

The two extension mixin classes carry per-language *constants* that
sit outside the Protocol surface but that downstream tasks (T2 RustStrategy,
T7 PythonStrategy) consume directly. Keeping them as separate classes
preserves SRP: the Protocol defines the contract, the mixins carry the
language-specific constant tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LanguageStrategy(Protocol):
    """Per-language plug-point consumed by the language-agnostic facades."""

    # Defaults are sentinels — every concrete strategy MUST override them.
    # Defaults exist so the names appear in ``inspect.getmembers`` for
    # registry-introspection callers; the empty-string / empty-frozenset
    # values are never used by production code paths.
    language_id: str = ""
    extension_allow_list: frozenset[str] = frozenset()
    code_action_allow_list: frozenset[str] = frozenset()

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Spawn (or fetch from the pool) the LSP servers this strategy needs.

        :param project_root: workspace root path; canonicalised by caller.
        :return: ``{server_id: SolidLanguageServer}`` ready for
            ``MultiServerCoordinator(servers=…)``. Single-server languages
            return ``{language_id: <server>}``; Python returns three entries.
        """
        ...


class RustStrategyExtensions:
    """Constants specific to ``RustStrategy`` (consumed in T2 + Stage 1G).

    rust-analyzer exposes its refactor catalogue as *assist* code actions
    under the ``refactor.<family>.assist`` kind hierarchy (per LSP §3.18.1
    sub-kinds). The whitelist below is the closed set of assist families
    Stage 1E commits to surfacing through the facade layer; future families
    require an explicit code change so the LLM surface remains stable.
    """

    EXTENSION_ALLOW_LIST: frozenset[str] = frozenset({".rs"})

    ASSIST_FAMILY_WHITELIST: frozenset[str] = frozenset({
        "refactor.extract",
        "refactor.inline",
        "refactor.rewrite",
        "refactor.move",
        "quickfix",
        "source.organizeImports",
    })


class PythonStrategyExtensions:
    """Constants specific to ``PythonStrategy`` (consumed in T7 + T8).

    SERVER_SET is the ordered tuple of server IDs Stage 1E spawns. Order
    matters only for diff-friendly test transcripts; priority across
    servers is decided by the Stage 1D ``_apply_priority()`` table, not
    by iteration order.

    pylsp-mypy is **deliberately absent** (Phase 0 P5a outcome C). Adding
    it back requires a deliberate code change so the regression is
    visible in code review.
    """

    EXTENSION_ALLOW_LIST: frozenset[str] = frozenset({".py", ".pyi"})

    SERVER_SET: tuple[str, ...] = ("pylsp-rope", "basedpyright", "ruff")

    # Code-action kinds the Python strategy considers in-scope. Any
    # action whose kind does not match (per LSP §3.18.1 prefix rule)
    # is filtered before merge.
    CODE_ACTION_ALLOW_LIST: frozenset[str] = frozenset({
        "quickfix",
        "refactor",
        "refactor.extract",
        "refactor.inline",
        "refactor.rewrite",
        "source.organizeImports",
        "source.fixAll",
    })

    # Q3: basedpyright 1.39.3 exact pin asserted at adapter spawn.
    BASEDPYRIGHT_VERSION_PIN: str = "1.39.3"

    # P3: Rope library bridge pin.
    ROPE_VERSION_PIN: str = "1.14.0"
