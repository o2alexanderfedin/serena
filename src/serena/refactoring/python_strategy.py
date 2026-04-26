"""Python refactoring strategy — Stage 1E §14.1 file 13.

Two halves land in two tasks:
  - T7 (this revision): multi-server orchestration via Stage 1D
    ``MultiServerCoordinator``. Three real LSPs spawned via Stage 1C
    ``LspPool``: pylsp-rope, basedpyright, ruff.
  - T8: 14-step interpreter discovery (specialist-python.md §7) +
    Rope library bridge (rope==1.14.0 per Phase 0 P3) appended.

Hard constraints (do not relax without re-running the relevant Phase 0 spike):
  - NO pylsp-mypy in SERVER_SET (Phase 0 P5a verdict C).
  - NO synthetic per-step didSave (Q1 cascade — pylsp-mypy mitigation
    became redundant once mypy was dropped).
  - basedpyright pinned to 1.39.3 (Phase 0 Q3).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .language_strategy import LanguageStrategy, PythonStrategyExtensions
from .lsp_pool import LspPool, LspPoolKey
from .multi_server import MultiServerCoordinator

log = logging.getLogger("serena.refactoring.python_strategy")


# Mapping from server-id (in SERVER_SET) to the synthetic language tag
# the LspPool keys on. Distinct tags force the pool to spawn distinct
# subprocesses for each LSP role — a single ``"python"`` tag would cause
# pool deduplication to collapse all three into one entry.
_SERVER_LANGUAGE_TAG: dict[str, str] = {
    "pylsp-rope": "python:pylsp-rope",
    "basedpyright": "python:basedpyright",
    "ruff": "python:ruff",
}


class PythonStrategy(LanguageStrategy, PythonStrategyExtensions):
    """Multi-server Python strategy: pylsp-rope + basedpyright + ruff.

    The Stage 1D ``MultiServerCoordinator`` consumes the three-server dict
    that ``build_servers`` returns. Per-call routing (broadcast for
    codeAction, single-primary for rename) lives in the coordinator;
    this class only owns the spawn topology.
    """

    language_id: str = "python"
    extension_allow_list: frozenset[str] = PythonStrategyExtensions.EXTENSION_ALLOW_LIST
    code_action_allow_list: frozenset[str] = PythonStrategyExtensions.CODE_ACTION_ALLOW_LIST

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Acquire one server per entry in ``SERVER_SET`` from the pool.

        Order in the returned dict mirrors ``SERVER_SET`` for diff-friendly
        test transcripts; coordinator priority does NOT depend on order.
        """
        out: dict[str, Any] = {}
        root_str = str(project_root)
        for server_id in self.SERVER_SET:
            tag = _SERVER_LANGUAGE_TAG[server_id]
            key = LspPoolKey(language=tag, project_root=root_str)
            out[server_id] = self._pool.acquire(key)
        return out

    def coordinator(self, project_root: Path) -> MultiServerCoordinator:
        """Build a ``MultiServerCoordinator`` over the three Python LSPs.

        Convenience factory: facades / MCP tools call
        ``strategy.coordinator(root)`` then dispatch through it.
        """
        return MultiServerCoordinator(servers=self.build_servers(project_root))
