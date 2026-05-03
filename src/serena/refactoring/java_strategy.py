"""Java refactoring strategy — Stream 6 / Leaf D.

Single-LSP strategy: jdtls (https://github.com/eclipse-jdtls/eclipse.jdt.ls)
is the canonical Java LSP for cross-file rename, extract, inline, generate,
and import-organisation operations.

Mirrors ``CppStrategy`` (the single-LSP reference for Stream 6 Leaf C):

  - identity constants (``language_id``, ``extension_allow_list``,
    ``code_action_allow_list``);
  - ``build_servers`` returns ``{"jdtls": <SolidLanguageServer>}``;
  - ``execute_command_whitelist()`` classmethod returns frozenset() — jdtls
    exposes its refactor operations exclusively via code actions, not via
    ``workspace/executeCommand`` verbs from the strategy layer.

jdtls is the richest Java LSP available — Eclipse JDT Language Server is
maintained by the Eclipse Foundation and is the backend used by VSCode's
Language Support for Java extension. It supports the full refactor surface:
extract method/variable/field/interface, inline, rewrite, generate constructors
/ hashCode+equals / toString / accessors / override stubs, organize imports,
and quick-fixes.

jdtls code action kinds (sourced from
https://github.com/eclipse-jdtls/eclipse.jdt.ls and LSP cap introspection
of ``JdtlsServer._get_initialize_params``):

  ``source.organizeImports``           — remove unused imports and sort.
  ``source.generate.constructor``      — generate constructor(s).
  ``source.generate.hashCodeEquals``   — generate hashCode / equals pair.
  ``source.generate.toString``         — generate toString() override.
  ``source.generate.accessors``        — generate getters and setters.
  ``source.generate.overrideMethods``  — generate override stubs.
  ``source.generate.delegateMethods``  — generate delegate method stubs.
  ``refactor.extract.method``          — extract selection to a new method.
  ``refactor.extract.variable``        — extract expression to a local variable.
  ``refactor.extract.field``           — extract expression to a field.
  ``refactor.extract.interface``       — extract interface from class.
  ``refactor.inline``                  — inline a local variable or method.
  ``refactor.rewrite``                 — rewrite (convert, invert, etc.).
  ``quickfix``                         — quick-fix offered diagnostics.
  ``refactor``                         — root parent kind (server may use for grouping).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy
from .lsp_pool import LspPool, LspPoolKey


# Single source of truth for the Java extension allow-list.
# jdtls handles all standard Java source file types.
_JAVA_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Standard Java source
        ".java",
    }
)

# Code action kinds that jdtls advertises and that the o2-scalpel facades will
# dispatch. Sourced from JdtlsServer._get_initialize_params codeActionKind
# valueSet (the client tells the server which kinds it understands; the server
# then only offers those). Kept as a frozenset to allow O(1) membership tests.
_JAVA_CODE_ACTION_KINDS: frozenset[str] = frozenset(
    {
        # import management
        "source.organizeImports",
        # code generation
        "source.generate.constructor",
        "source.generate.hashCodeEquals",
        "source.generate.toString",
        "source.generate.accessors",
        "source.generate.overrideMethods",
        "source.generate.delegateMethods",
        # extract refactors
        "refactor.extract",
        "refactor.extract.method",
        "refactor.extract.variable",
        "refactor.extract.field",
        "refactor.extract.interface",
        # v1.5 P2 — scalpel_extract Java-arm dispatch kinds. jdtls advertises
        # ``refactor.extract.method`` natively; LSP §3.18.1 prefix matching
        # routes the family-shaped ``refactor.extract.function`` /
        # ``refactor.extract.constant`` requests onto the matching server-side
        # actions. The allow-list entries here are required so the catalog
        # carries them and ``MultiServerCoordinator.supports_kind`` returns
        # True for the Java arm of ``ExtractTool``.
        "refactor.extract.function",
        "refactor.extract.constant",
        # inline refactors
        "refactor.inline",
        # rewrite refactors
        "refactor.rewrite",
        # quickfix
        "quickfix",
        # generic refactor parent kind
        "refactor",
    }
)


class JavaStrategy(LanguageStrategy):
    """Single-LSP ``LanguageStrategy`` for Java (jdtls).

    The strategy is intentionally single-LSP — jdtls covers the complete
    refactor surface for Java: rename, extract, inline, rewrite, import-
    organisation, code generation, and quick-fixes. jdtls is the canonical
    Java language server maintained by the Eclipse Foundation at
    https://github.com/eclipse-jdtls/eclipse.jdt.ls.
    """

    language_id: str = "java"
    extension_allow_list: frozenset[str] = _JAVA_EXTENSIONS
    code_action_allow_list: frozenset[str] = _JAVA_CODE_ACTION_KINDS

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"jdtls": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry. The pool's
        spawn function wraps the spawned server in ``_AsyncAdapter`` so that
        ``MultiServerCoordinator.broadcast`` can ``await`` the facade methods.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"jdtls": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs this strategy
        will dispatch.

        jdtls exposes its refactor surface exclusively through code actions
        (``textDocument/codeAction``), not via ``workspace/executeCommand``
        from the strategy layer. The whitelist is therefore empty. If a
        future jdtls release adds execute-command verbs they land here —
        keeping the table next to the strategy preserves the single-source-
        of-truth invariant.
        """
        return frozenset()
