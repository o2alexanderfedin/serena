"""Per-(language, project_root) LSP pool (Stage 1C §14.1 file 8).

The pool sits behind the deferred-loading surface (§6.10 / §12.2): a language
facade calls ``pool.acquire(LspPoolKey(language, project_root))`` and gets a
fully-initialised ``SolidLanguageServer`` whose underlying child process is
spawned on first use, kept warm across calls, recycled when the pre-ping
health probe fails (T4), and reaped after
``O2_SCALPEL_LSP_IDLE_SHUTDOWN_SECONDS`` of inactivity (T3). The §16.1 RAM
ceiling is enforced before every spawn (T5); the guard refuses with
``WaitingForLspBudget`` when over budget rather than crashing the user's
editor.

T2 lands the lifecycle skeleton (acquire/release/shutdown_all + per-key
spawn lock + stats). T3..T8 layer reaper / pre-ping / budget / discovery /
transaction-affinity / telemetry.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("serena.refactoring.lsp_pool")


@dataclass(frozen=True, slots=True)
class LspPoolKey:
    """Canonical (language, project_root) tuple used as a pool dict key.

    ``project_root`` is canonicalised at construction via
    ``Path.expanduser().resolve(strict=False)``; relative paths, ``~``
    expansion, symlinks, and trailing slashes all collapse to the same key.
    """

    language: str
    project_root: str
    project_root_path: Path = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        resolved = Path(self.project_root).expanduser().resolve(strict=False)
        object.__setattr__(self, "project_root_path", resolved)
        object.__setattr__(self, "project_root", str(resolved))


@dataclass
class _ServerEntry:
    """Internal: one (server, last_used_ts, inflight, entry_lock) tuple."""
    server: Any  # SolidLanguageServer or fake; opaque to the pool.
    inflight: int = 0
    last_used_ts: float = 0.0
    entry_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class PoolStats:
    """Snapshot of pool internal counters; safe to expose on tools/health."""
    active_servers: int
    inflight: dict[LspPoolKey, int]
    spawn_count: int
    pre_ping_fail_count: int = 0
    idle_reaped_count: int = 0
    budget_reject_count: int = 0


class LspPool:
    """In-memory pool of ``SolidLanguageServer`` instances keyed by ``LspPoolKey``."""

    def __init__(
        self,
        spawn_fn: Callable[[LspPoolKey], Any],
        idle_shutdown_seconds: float,
        ram_ceiling_mb: float,
        reaper_enabled: bool = True,
    ) -> None:
        """:param spawn_fn: factory invoked once per (key) miss to create a server.
        :param idle_shutdown_seconds: how long an entry can sit at inflight=0
            before the reaper (T3) calls .stop() on it.
        :param ram_ceiling_mb: §16.1 hard ceiling; new spawn refused above this.
        :param reaper_enabled: whether to start the background reaper thread.
            Tests pass ``False`` to keep the per-test state deterministic.
        """
        self._spawn_fn = spawn_fn
        self._idle_seconds = idle_shutdown_seconds
        self._ram_ceiling_mb = ram_ceiling_mb
        self._reaper_enabled = reaper_enabled
        self._entries: OrderedDict[LspPoolKey, _ServerEntry] = OrderedDict()
        self._pool_lock = threading.Lock()
        self._spawn_count = 0
        self._pre_ping_fail_count = 0
        self._idle_reaped_count = 0
        self._budget_reject_count = 0

    # --- public API ------------------------------------------------------

    def acquire(self, key: LspPoolKey) -> Any:
        """Return the server for ``key``; spawn lazily on miss.

        Concurrent ``acquire(same key)`` calls share one spawn — guarded by a
        per-entry lock obtained under the pool lock.
        """
        # Phase 1: locate-or-create the entry under the global lock. We may
        # release it before spawning (spawn is slow; we don't want it to
        # block other keys).
        with self._pool_lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _ServerEntry(server=None)
                self._entries[key] = entry
            entry.inflight += 1
            entry_lock = entry.entry_lock

        # Phase 2: spawn if necessary, under the per-entry lock.
        with entry_lock:
            if entry.server is None:
                log.info("LspPool spawn key=%s", key)
                entry.server = self._spawn_fn(key)
                self._spawn_count += 1
        # Update bookkeeping under the global lock so stats() is consistent.
        with self._pool_lock:
            entry.last_used_ts = self._now()
            self._entries.move_to_end(key)
        return entry.server

    def release(self, key: LspPoolKey) -> None:
        """Decrement the in-flight counter for ``key``; reaper-eligible at 0."""
        with self._pool_lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if entry.inflight > 0:
                entry.inflight -= 1
            entry.last_used_ts = self._now()

    def shutdown_all(self) -> None:
        """Stop every server and clear the pool. Idempotent."""
        with self._pool_lock:
            entries = list(self._entries.values())
            self._entries.clear()
        # Drop the lock before calling stop() — the lifecycle methods may
        # block on the LSP child process.
        for entry in entries:
            srv = entry.server
            if srv is not None:
                try:
                    srv.stop()
                except Exception:  # pragma: no cover - best-effort cleanup
                    log.exception("LspPool.shutdown_all: stop() raised")

    def stats(self) -> PoolStats:
        """Snapshot of current pool counters (thread-safe; copies in-flight dict)."""
        with self._pool_lock:
            return PoolStats(
                active_servers=sum(1 for e in self._entries.values() if e.server is not None),
                inflight={k: e.inflight for k, e in self._entries.items()},
                spawn_count=self._spawn_count,
                pre_ping_fail_count=self._pre_ping_fail_count,
                idle_reaped_count=self._idle_reaped_count,
                budget_reject_count=self._budget_reject_count,
            )

    # --- internals -------------------------------------------------------

    @staticmethod
    def _now() -> float:
        import time
        return time.monotonic()
