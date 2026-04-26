"""Stage 1G — ``ScalpelRuntime`` singleton.

The runtime owns the *process-global* state the 8 primitive tools share:

  - ``CheckpointStore`` (LRU 50, Stage 1B default).
  - ``TransactionStore`` (LRU 20, bound to the above CheckpointStore).
  - ``LspPool`` per ``(Language, project_root)`` key (Stage 1C).
  - ``CapabilityCatalog`` cached after first ``catalog()`` call (Stage 1F).
  - ``MultiServerCoordinator`` factory keyed by ``Language`` (Stage 1D).

Process-global is justified because:
  - Tools are constructed by the MCP factory once per server lifetime.
  - The pool, stores, and catalog are themselves designed to be shared
    across tools (Stage 1B/1C/1F all assert process-global semantics).
  - Tests use ``reset_for_testing()`` to restore between cases.

Thread-safe via a single ``threading.Lock``. Lazy: nothing is built
until the first call.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from serena.refactoring import (
    STRATEGY_REGISTRY,
    CheckpointStore,
    LspPool,
    LspPoolKey,
    MultiServerCoordinator,
    TransactionStore,
)
from serena.refactoring.capabilities import CapabilityCatalog, build_capability_catalog

if TYPE_CHECKING:
    from solidlsp.ls_config import Language


def _default_spawn_fn(key: LspPoolKey) -> Any:
    """Stage 1G placeholder spawn callback.

    The Stage 2A ergonomic facades replace this with a real
    ``solidlsp.factory``-driven spawner. Stage 1G's tests never
    ``acquire`` so this body is unreachable in unit-test paths;
    raising preserves a clear contract.
    """
    raise NotImplementedError(
        f"ScalpelRuntime spawn_fn is a placeholder for {key!r}; Stage 2A "
        f"wires the real solidlsp factory. Tests should not acquire from "
        f"this pool."
    )


class ScalpelRuntime:
    """Lazy, process-global runtime shared by the 8 Stage 1G tools."""

    _instance: ClassVar["ScalpelRuntime | None"] = None
    _instance_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._checkpoint_store: CheckpointStore | None = None
        self._transaction_store: TransactionStore | None = None
        self._catalog: CapabilityCatalog | None = None
        self._pools: dict[tuple[str, Path], LspPool] = {}
        self._coordinators: dict[tuple[str, Path], MultiServerCoordinator] = {}

    # --- singleton accessors -----------------------------------------

    @classmethod
    def instance(cls) -> "ScalpelRuntime":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_for_testing(cls) -> None:
        """Drop the singleton (and shut down any pooled servers).

        Tests MUST call this in setUp/tearDown to keep state isolated.
        Production paths MUST NOT call this.
        """
        with cls._instance_lock:
            inst = cls._instance
            if inst is not None:
                with inst._lock:
                    for pool in inst._pools.values():
                        try:
                            pool.shutdown_all()
                        except Exception:  # pragma: no cover — best-effort
                            pass
            cls._instance = None

    # --- lazy state --------------------------------------------------

    def checkpoint_store(self) -> CheckpointStore:
        with self._lock:
            if self._checkpoint_store is None:
                self._checkpoint_store = CheckpointStore()
            return self._checkpoint_store

    def transaction_store(self) -> TransactionStore:
        # Build the checkpoint store first (acquires its own lock briefly).
        ckpt = self.checkpoint_store()
        with self._lock:
            if self._transaction_store is None:
                self._transaction_store = TransactionStore(
                    checkpoint_store=ckpt,
                )
            return self._transaction_store

    def catalog(self) -> CapabilityCatalog:
        with self._lock:
            if self._catalog is None:
                self._catalog = build_capability_catalog(
                    STRATEGY_REGISTRY, project_root=None,
                )
            return self._catalog

    def pool_for(self, language: "Language", project_root: Path) -> LspPool:
        canon_root = project_root.expanduser().resolve(strict=False)
        key = (language.value, canon_root)
        with self._lock:
            existing = self._pools.get(key)
            if existing is not None:
                return existing
            pool = LspPool(
                spawn_fn=_default_spawn_fn,
                idle_shutdown_seconds=None,
                ram_ceiling_mb=float(
                    os.environ.get("O2_SCALPEL_LSP_RAM_CEILING_MB", "8192"),
                ),
                reaper_enabled=False,
                pre_ping_on_acquire=True,
                events_path=None,
            )
            self._pools[key] = pool
            return pool

    def coordinator_for(
        self,
        language: "Language",
        project_root: Path,
    ) -> MultiServerCoordinator:
        canon_root = project_root.expanduser().resolve(strict=False)
        key = (language.value, canon_root)
        with self._lock:
            existing = self._coordinators.get(key)
            if existing is not None:
                return existing
        # Build outside the runtime lock — strategy.build_servers can be
        # slow (real LSP spawn) and we don't want to hold the lock for it.
        pool = self.pool_for(language, canon_root)
        strategy_cls = STRATEGY_REGISTRY[language]
        strategy = strategy_cls(pool=pool)
        servers = strategy.build_servers(canon_root)
        coord = MultiServerCoordinator(servers=servers)
        with self._lock:
            # Re-check under lock in case another thread won the race.
            existing = self._coordinators.get(key)
            if existing is not None:
                return existing
            self._coordinators[key] = coord
            return coord


__all__ = ["ScalpelRuntime"]
