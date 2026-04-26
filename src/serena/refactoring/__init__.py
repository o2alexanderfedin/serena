"""Stage 1B + Stage 1D refactoring substrate.

Three sibling concerns:
- ``inverse_workspace_edit`` synthesizes the reverse of a successfully-applied
  ``WorkspaceEdit`` so a checkpoint can roll forward through the same applier.
- ``CheckpointStore`` keeps an LRU(50) of (applied_edit, snapshot, inverse) tuples.
- ``TransactionStore`` keeps an LRU(20) of checkpoint groupings; rollback walks
  member checkpoints in reverse order. (Added in T12.)
- Multi-server coordination (Stage 1D T1–T9) exports merger schemas: ``MergedCodeAction``,
  ``SuppressedAlternative``, ``ServerTimeoutWarning``, ``MultiServerBroadcastResult``.
"""

from .checkpoints import CheckpointStore, inverse_workspace_edit
from .discovery import PluginRecord, default_cache_root, discover_sibling_plugins, enabled_languages
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
from .transactions import TransactionStore

__all__ = [
    "CheckpointStore",
    "EditAttributionLog",
    "LspPool",
    "LspPoolKey",
    "MergedCodeAction",
    "MultiServerBroadcastResult",
    "MultiServerCoordinator",
    "PluginRecord",
    "PoolEvent",
    "PoolStats",
    "ProvenanceLiteral",
    "ServerTimeoutWarning",
    "SuppressedAlternative",
    "TransactionStore",
    "WaitingForLspBudget",
    "default_cache_root",
    "discover_sibling_plugins",
    "enabled_languages",
    "inverse_workspace_edit",
]
