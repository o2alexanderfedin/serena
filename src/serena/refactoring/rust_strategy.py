"""Rust refactoring strategy (§14.1 file 12).

``RustStrategy`` is the Protocol-conformant binding between
``MultiServerCoordinator`` and the rust-analyzer + clippy LSP servers.
It owns the rust-side identity constants, fetches servers from the
Stage 1C ``LspPool``, and exposes the v1.4 surface used by all 25 Rust
ergonomic facades:

  * assist invocation through ``textDocument/codeAction`` + the
    rust-analyzer experimental extensions (``rust-analyzer/expandMacro``,
    ``experimental/runnables``, ``rust-analyzer/runFlycheck``),
  * clippy multi-server merging via the §11.3 priority table,
  * snippet rendering and ChangeAnnotation passthrough,
  * the execute-command whitelist below (mirrored as the single source of
    truth for ``serena.tools.scalpel_primitives._EXECUTE_COMMAND_WHITELIST``).

Historical note: this module shipped as a Stage-1E skeleton; the body was
filled out across Stage 1G (assist + clippy wiring), v0.2.0 (multi-server
merge) and v1.1 (Stream-5 facade fleet). v1.5 LO-2 updates this docstring
to match the current state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy, RustStrategyExtensions
from .lsp_pool import LspPool, LspPoolKey


# Default rust-analyzer execute-command verbs (always reachable through
# scalpel_execute_command). Mirrors the Rust entry in
# ``serena.tools.scalpel_primitives._EXECUTE_COMMAND_WHITELIST`` but is
# computed here so the strategy's whitelist contract sits next to the
# strategy itself (single source of truth per CLAUDE.md).
_DEFAULT_RUST_EXECUTE_COMMAND_WHITELIST: frozenset[str] = frozenset({
    "rust-analyzer.runFlycheck",
    "rust-analyzer.cancelFlycheck",
    "rust-analyzer.clearFlycheck",
    "rust-analyzer.reloadWorkspace",
    "rust-analyzer.rebuildProcMacros",
    "rust-analyzer.expandMacro",
    "rust-analyzer.viewSyntaxTree",
    "rust-analyzer.viewHir",
    "rust-analyzer.viewMir",
    "rust-analyzer.viewItemTree",
    "rust-analyzer.viewCrateGraph",
    "rust-analyzer.relatedTests",
})


# Verbs that become reachable only when ``O2_SCALPEL_CLIPPY_MULTI_SERVER``
# is set. Clippy's auto-rewrite mode bypasses the multi-server merger and
# the workspace-boundary gate (it writes through cargo's own file IO)
# so the verb is OFF by default and requires an explicit opt-in.
_CLIPPY_MULTI_SERVER_VERBS: frozenset[str] = frozenset({
    "cargo.clippy.applyFix",
})

_CLIPPY_MULTI_SERVER_FEATURE_FLAG: str = "O2_SCALPEL_CLIPPY_MULTI_SERVER"


def _feature_flag_enabled(name: str) -> bool:
    """Truthy values: ``1``, ``true``, ``yes``, ``on`` (case-insensitive)."""
    raw = os.environ.get(name, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class RustStrategy(LanguageStrategy, RustStrategyExtensions):
    """Skeleton ``LanguageStrategy`` for Rust (rust-analyzer single LSP).

    Stage 1G will fill in:
      - assist code-action invocation surface,
      - clippy as a second LSP for diagnostic enrichment (parallel to the
        Python multi-server pattern but with a smaller priority table),
      - snippet rendering for whole-file ``ChangeAnnotation`` payloads.
    """

    language_id: str = "rust"
    extension_allow_list: frozenset[str] = RustStrategyExtensions.EXTENSION_ALLOW_LIST

    # Family-level entries; LSP §3.18.1 prefix matching means rust-analyzer's
    # "refactor.extract.assist" auto-matches "refactor.extract" here.
    code_action_allow_list: frozenset[str] = RustStrategyExtensions.ASSIST_FAMILY_WHITELIST

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Return ``{"rust-analyzer": <SolidLanguageServer>}`` from the pool.

        Single-LSP language; the dict has exactly one entry. Stage 1G will
        extend this to ``{"rust-analyzer": ..., "clippy": ...}`` once the
        clippy-LSP adapter lands.
        """
        key = LspPoolKey(language=self.language_id, project_root=str(project_root))
        server = self._pool.acquire(key)
        return {"rust-analyzer": server}

    @classmethod
    def execute_command_whitelist(cls) -> frozenset[str]:
        """Return the set of ``workspace/executeCommand`` verbs the Rust
        strategy will dispatch.

        Always includes the rust-analyzer default surface
        (``_DEFAULT_RUST_EXECUTE_COMMAND_WHITELIST``). Adds the
        clippy multi-server verbs (``_CLIPPY_MULTI_SERVER_VERBS``) ONLY
        when the ``O2_SCALPEL_CLIPPY_MULTI_SERVER`` env var is truthy —
        clippy's auto-rewrite mode bypasses the language-agnostic
        merger and workspace-boundary gate, so it is opt-in per
        v1.1 Stream-5 Leaf-04.
        """
        if _feature_flag_enabled(_CLIPPY_MULTI_SERVER_FEATURE_FLAG):
            return _DEFAULT_RUST_EXECUTE_COMMAND_WHITELIST | _CLIPPY_MULTI_SERVER_VERBS
        return _DEFAULT_RUST_EXECUTE_COMMAND_WHITELIST
