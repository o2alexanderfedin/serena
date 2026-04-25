"""Stage 1B refactoring substrate.

Three sibling concerns:
- ``inverse_workspace_edit`` synthesizes the reverse of a successfully-applied
  ``WorkspaceEdit`` so a checkpoint can roll forward through the same applier.
- ``CheckpointStore`` keeps an LRU(50) of (applied_edit, snapshot, inverse) tuples.
- ``TransactionStore`` keeps an LRU(20) of checkpoint groupings; rollback walks
  member checkpoints in reverse order. (Added in T12.)
"""

from .checkpoints import CheckpointStore, inverse_workspace_edit
from .transactions import TransactionStore

__all__ = ["CheckpointStore", "TransactionStore", "inverse_workspace_edit"]
