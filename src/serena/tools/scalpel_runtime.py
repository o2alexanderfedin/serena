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

import asyncio
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
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
from serena.plugins.registry import PluginRegistry
from serena.refactoring._async_check import AWAITED_SERVER_METHODS
from serena.refactoring.capabilities import CapabilityCatalog, build_capability_catalog
from serena.refactoring.checkpoint_default_root import default_checkpoint_disk_root
from serena.refactoring.pending_tx import DiskPendingTxStore
from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry

if TYPE_CHECKING:
    from solidlsp.ls_config import Language


# ---------------------------------------------------------------------------
# Stage 2A — real ``solidlsp`` spawn factory.
#
# Replaces the Stage 1G placeholder. The dispatch table maps the four
# ``LspPoolKey.language`` string tags emitted by Stage 1E strategies to the
# adapter class that knows how to talk to the corresponding language server.
# Each spawned server is wrapped with ``_AsyncAdapter`` so that
# ``MultiServerCoordinator.broadcast`` (which awaits ``facade(**kwargs)``)
# works against the sync ``SolidLanguageServer`` facades. _FakeServer
# instances used by Stage 1D unit tests are already async, so they bypass the
# wrapper naturally.
# ---------------------------------------------------------------------------


class _AsyncAdapter:
    """Wrap a sync ``SolidLanguageServer`` so coroutine-based callers work.

    The Stage 1A LSP facade methods (``request_code_actions``,
    ``resolve_code_action``, ``execute_command``,
    ``request_rename_symbol_edit``) are synchronous on the real
    ``SolidLanguageServer``. ``MultiServerCoordinator.broadcast`` awaits
    ``getattr(server, facade_name)(**kwargs)`` — meaning the real adapter
    blows up because the result is not awaitable. This adapter exposes the
    same attribute names but each call returns a coroutine that runs the
    blocking work on a thread via ``asyncio.to_thread``.
    """

    __slots__ = ("_inner",)

    # Facade method names that need async wrapping. Canonical definition
    # lives in ``serena.refactoring._async_check.AWAITED_SERVER_METHODS``
    # and is shared with ``MultiServerCoordinator._AWAITED_SERVER_METHODS``
    # (single source of truth per CLAUDE.md).
    _ASYNC_METHODS = frozenset(AWAITED_SERVER_METHODS)

    def __init__(self, inner: Any) -> None:
        object.__setattr__(self, "_inner", inner)

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if name in self._ASYNC_METHODS and callable(target):
            async def _async_call(*args: Any, **kwargs: Any) -> Any:
                return await asyncio.to_thread(target, *args, **kwargs)
            return _async_call
        return target

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return f"_AsyncAdapter({self._inner!r})"


def _build_language_server_config(language_value: str) -> Any:
    """Construct a LanguageServerConfig matching the pool key.

    The legacy ``code_language`` field on LanguageServerConfig is the only
    required input; everything else has a sane default for spawn purposes.
    """
    from solidlsp.ls_config import Language, LanguageServerConfig
    return LanguageServerConfig(code_language=Language(language_value))


def _build_solidlsp_settings() -> Any:
    """Construct a SolidLSPSettings instance for the spawned server."""
    from solidlsp.settings import SolidLSPSettings
    return SolidLSPSettings()


def _spawn_rust_analyzer(key: LspPoolKey) -> Any:
    from solidlsp.language_servers.rust_analyzer import RustAnalyzer
    server = RustAnalyzer(
        config=_build_language_server_config("rust"),
        repository_root_path=key.project_root,
        solidlsp_settings=_build_solidlsp_settings(),
    )
    server.start()
    return _AsyncAdapter(server)


def _spawn_pylsp(key: LspPoolKey) -> Any:
    from solidlsp.language_servers.pylsp_server import PylspServer
    server = PylspServer(
        config=_build_language_server_config("python"),
        repository_root_path=key.project_root,
        solidlsp_settings=_build_solidlsp_settings(),
    )
    server.start()
    return _AsyncAdapter(server)


def _spawn_basedpyright(key: LspPoolKey) -> Any:
    from solidlsp.language_servers.basedpyright_server import BasedpyrightServer
    server = BasedpyrightServer(
        config=_build_language_server_config("python"),
        repository_root_path=key.project_root,
        solidlsp_settings=_build_solidlsp_settings(),
    )
    server.start()
    return _AsyncAdapter(server)


def _spawn_ruff(key: LspPoolKey) -> Any:
    from solidlsp.language_servers.ruff_server import RuffServer
    server = RuffServer(
        config=_build_language_server_config("python"),
        repository_root_path=key.project_root,
        solidlsp_settings=_build_solidlsp_settings(),
    )
    server.start()
    return _AsyncAdapter(server)


def _spawn_marksman(key: LspPoolKey) -> Any:
    """v1.1.1 Leaf 02 — spawn marksman for ``MarkdownStrategy.build_servers``.

    The strategy is single-LSP (markdown has only one credible LSP at the
    moment), so the dispatch table key is the bare ``"markdown"`` tag —
    no ``markdown:marksman`` subtag is needed today. If a second markdown
    LSP ever joins the strategy, follow the Python pattern and split into
    ``markdown:marksman`` / ``markdown:<other>`` tags then.
    """
    from solidlsp.language_servers.marksman_server import MarksmanLanguageServer
    server = MarksmanLanguageServer(
        config=_build_language_server_config("markdown"),
        repository_root_path=key.project_root,
        solidlsp_settings=_build_solidlsp_settings(),
    )
    server.start()
    return _AsyncAdapter(server)


_SPAWN_DISPATCH_TABLE: dict[str, Callable[[LspPoolKey], Any]] = {
    "rust": _spawn_rust_analyzer,
    "python:pylsp-rope": _spawn_pylsp,
    "python:basedpyright": _spawn_basedpyright,
    "python:ruff": _spawn_ruff,
    "markdown": _spawn_marksman,
}


def _default_spawn_fn(key: LspPoolKey) -> Any:
    """Real solidlsp factory — dispatches by LspPoolKey.language string tag.

    Replaces the Stage 1G placeholder. The four valid tags mirror Stage 1E's
    ``PythonStrategy._SERVER_LANGUAGE_TAG`` (python:pylsp-rope /
    python:basedpyright / python:ruff) plus the single ``rust`` tag emitted
    by ``RustStrategy.build_servers``. Each spawned server is wrapped with
    ``_AsyncAdapter`` so ``MultiServerCoordinator.broadcast`` works against
    sync ``SolidLanguageServer`` facades.
    """
    fn = _SPAWN_DISPATCH_TABLE.get(key.language)
    if fn is None:
        raise ValueError(
            f"ScalpelRuntime spawn_fn: unknown LspPoolKey.language tag "
            f"{key.language!r} for project_root={key.project_root!r}; "
            f"expected one of {sorted(_SPAWN_DISPATCH_TABLE)}."
        )
    return fn(key)


def parse_workspace_extra_paths() -> tuple[str, ...]:
    """Parse ``O2_SCALPEL_WORKSPACE_EXTRA_PATHS`` (Q4 §11.8 opt-in).

    Splits on ``os.pathsep``, drops blank entries, returns a tuple. Consumers
    pass this to ``SolidLanguageServer.is_in_workspace(target, roots,
    extra_paths=...)``.
    """
    raw = os.environ.get("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", "")
    if not raw:
        return ()
    return tuple(p for p in raw.split(os.pathsep) if p.strip())


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
        self._dynamic_capability_registry: DynamicCapabilityRegistry | None = None
        self._plugin_registry: PluginRegistry | None = None
        self._pending_tx_store: DiskPendingTxStore | None = None
        # v1.1 Stream 5 / Leaf 05 — resolve the engine knob at runtime
        # construction so an unknown ``O2_SCALPEL_ENGINE`` value fails
        # fast (Settings validator raises ValidationError) rather than
        # silently degrading at first use. Lazy import of the Settings
        # module avoids pulling pydantic-settings into every consumer
        # of ``serena.tools.scalpel_runtime`` at module-load time.
        from serena.config.engine import Settings

        self.engine_id: str = Settings().engine

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
        """Lazy-build the singleton checkpoint store.

        v1.1 Stream 5 / Leaf 02 (S3 critic guard): production callers MUST
        receive a ``disk_root`` so checkpoints survive process restart.
        The root resolves via ``default_checkpoint_disk_root()`` —
        ``O2_SCALPEL_CACHE`` env override → platformdirs user cache fallback.
        Tests bypassing persistence go through ``CheckpointStore()`` directly,
        not this factory.
        """
        with self._lock:
            if self._checkpoint_store is None:
                self._checkpoint_store = CheckpointStore(
                    disk_root=default_checkpoint_disk_root(),
                )
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

    def pending_tx_store(self) -> DiskPendingTxStore:
        """Lazy-build the singleton pending-tx store (Leaf 06).

        Backs ``confirmation_mode='manual'`` for ``scalpel_dry_run_compose``
        and the new ``scalpel_confirm_annotations`` MCP tool. The on-disk
        root is a sibling of the checkpoint root (``<cache>/pending_tx``)
        so the two stores cannot accidentally collide on ids while still
        sharing the ``O2_SCALPEL_CACHE`` env override.
        """
        with self._lock:
            if self._pending_tx_store is None:
                ckpt_root = default_checkpoint_disk_root()
                self._pending_tx_store = DiskPendingTxStore(
                    root=ckpt_root.parent / "pending_tx",
                )
            return self._pending_tx_store

    def plugin_registry(self) -> PluginRegistry:
        """Lazy-build the singleton plugin registry.

        v1.1 Stream 5 / Leaf 03 — backs ``scalpel_reload_plugins``. The
        plugins root resolves via ``O2_SCALPEL_PLUGINS_ROOT`` env override
        → current working directory fallback. The registry is constructed
        empty; the first ``reload()`` call populates state from disk so
        startup stays cheap (Q10: explicit-refresh model).
        """
        with self._lock:
            if self._plugin_registry is None:
                root = Path(
                    os.environ.get("O2_SCALPEL_PLUGINS_ROOT", str(Path.cwd())),
                ).expanduser().resolve(strict=False)
                self._plugin_registry = PluginRegistry(root)
            return self._plugin_registry

    def set_plugin_registry_for_testing(
        self, registry: PluginRegistry,
    ) -> None:
        """Replace the in-memory plugin registry; tests only.

        Production paths must use :meth:`plugin_registry`. The companion
        :meth:`reset_for_testing` drops the singleton entirely; this
        accessor is a finer-grained hook for tests that want a custom
        ``plugins_dir`` without rebuilding the rest of the runtime.
        """
        with self._lock:
            self._plugin_registry = registry

    def dynamic_capability_registry(self) -> DynamicCapabilityRegistry:
        """Process-global registry of LSP ``client/registerCapability``
        events, populated by ``SolidLanguageServer._handle_register_capability``
        and surfaced by ``workspace_health``. Lazy; reset by
        ``reset_for_testing()``.
        """
        with self._lock:
            if self._dynamic_capability_registry is None:
                self._dynamic_capability_registry = DynamicCapabilityRegistry()
            return self._dynamic_capability_registry

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
        coord = MultiServerCoordinator(
            servers=servers,
            dynamic_registry=self.dynamic_capability_registry(),
            catalog=self.catalog(),
        )
        with self._lock:
            # Re-check under lock in case another thread won the race.
            existing = self._coordinators.get(key)
            if existing is not None:
                return existing
            self._coordinators[key] = coord
            return coord

    def editor_for_workspace(
        self,
        language: "Language",
        project_root: Path,
    ) -> "WorkspaceEditor":
        """Return a typed ``WorkspaceEditor`` for the given workspace.

        Backlog #7 (v0.2.0). Bundles the per-(language, project_root)
        ``MultiServerCoordinator`` with the Q4 workspace-boundary helper so
        callers can ask for an editor instead of threading the coordinator
        and the boundary check through call sites.
        """
        canon_root = project_root.expanduser().resolve(strict=False)
        coord = self.coordinator_for(language, canon_root)
        return WorkspaceEditor(coordinator=coord, project_root=canon_root)


@dataclass(frozen=True)
class WorkspaceEditor:
    """Workspace-scoped editor handle returned by ``editor_for_workspace``.

    Wraps the ``MultiServerCoordinator`` plus the Q4 workspace-boundary
    helper. ``project_root`` is the canonicalised root the editor is
    bound to; ``is_in_workspace`` admits paths under it (plus any
    ``O2_SCALPEL_WORKSPACE_EXTRA_PATHS`` opt-ins).
    """

    coordinator: MultiServerCoordinator
    project_root: Path

    def is_in_workspace(self, target: Path) -> bool:
        """Boundary check matching ``SolidLanguageServer.is_in_workspace``."""
        from solidlsp.ls import SolidLanguageServer
        return SolidLanguageServer.is_in_workspace(
            str(target),
            [str(self.project_root)],
            extra_paths=list(parse_workspace_extra_paths()),
        )


__all__ = ["ScalpelRuntime", "WorkspaceEditor"]
