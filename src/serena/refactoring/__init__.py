"""Stage 1B + 1C + 1D + 1E refactoring substrate.

Stage 1E adds:
- ``LanguageStrategy`` Protocol + Rust/Python extension mixin classes.
- ``RustStrategy`` (skeleton; full body in Stage 1G).
- ``PythonStrategy`` with three-LSP orchestration + 14-step interpreter
  discovery + Rope library bridge.
- ``STRATEGY_REGISTRY`` for ``Language → strategy class`` lookup.
"""

from .capabilities import (
    CapabilityCatalog,
    CapabilityRecord,
    CatalogIntrospectionError,
    build_capability_catalog,
)
from .checkpoints import CheckpointStore, inverse_workspace_edit
from .discovery import PluginRecord, default_cache_root, discover_sibling_plugins, enabled_languages
from .language_strategy import (
    LanguageStrategy,
    PythonStrategyExtensions,
    RustStrategyExtensions,
)
from .lsp_pool import LspPool, LspPoolKey, PoolEvent, PoolStats, WaitingForLspBudget
from .multi_server import (
    EditAttributionLog,
    MergedCodeAction,
    MultiServerBroadcastResult,
    MultiServerCoordinator,
    ProvenanceLiteral,
    ServerTimeoutWarning,
    SuppressedAlternative,
)
from .markdown_strategy import MarkdownStrategy
from .python_strategy import (
    ChangeSignatureSpec,
    PythonInterpreterNotFound,
    PythonStrategy,
    RopeBridgeError,
)
from .rust_strategy import RustStrategy
from .transactions import TransactionStore
from .golang_strategy import GolangStrategy
from .typescript_strategy import TypescriptStrategy
from .cpp_strategy import CppStrategy
from .java_strategy import JavaStrategy
from .lean_strategy import LeanStrategy


# Lazy-import the Language enum to keep refactoring/__init__.py free of
# any solidlsp transitive imports at module-load time.
def _build_strategy_registry() -> dict:
    from solidlsp.ls_config import Language
    return {
        Language.PYTHON: PythonStrategy,
        Language.RUST: RustStrategy,
        Language.MARKDOWN: MarkdownStrategy,
        Language.TYPESCRIPT: TypescriptStrategy,
        Language.GO: GolangStrategy,
        Language.CPP: CppStrategy,
        Language.JAVA: JavaStrategy,
        Language.LEAN4: LeanStrategy,
    }


STRATEGY_REGISTRY = _build_strategy_registry()


__all__ = [
    "CapabilityCatalog",
    "CapabilityRecord",
    "CatalogIntrospectionError",
    "ChangeSignatureSpec",
    "CheckpointStore",
    "EditAttributionLog",
    "LanguageStrategy",
    "LspPool",
    "LspPoolKey",
    "MarkdownStrategy",
    "MergedCodeAction",
    "MultiServerBroadcastResult",
    "MultiServerCoordinator",
    "PluginRecord",
    "PoolEvent",
    "PoolStats",
    "ProvenanceLiteral",
    "PythonInterpreterNotFound",
    "PythonStrategy",
    "PythonStrategyExtensions",
    "RopeBridgeError",
    "RustStrategy",
    "RustStrategyExtensions",
    "STRATEGY_REGISTRY",
    "ServerTimeoutWarning",
    "SuppressedAlternative",
    "TransactionStore",
    "GolangStrategy",
    "TypescriptStrategy",
    "CppStrategy",
    "JavaStrategy",
    "LeanStrategy",
    "WaitingForLspBudget",
    "build_capability_catalog",
    "default_cache_root",
    "discover_sibling_plugins",
    "enabled_languages",
    "inverse_workspace_edit",
]
