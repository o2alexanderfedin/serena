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


class WaitingForLspBudget(RuntimeError):
    """Raised by ``LspPool.acquire`` when a new spawn would exceed the §16 RAM ceiling.

    The error message is structured so callers can surface the actual /
    allowed numbers to the user: ``"<actual_mb> > ceiling <ceiling_mb>"``.
    """


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
        idle_shutdown_seconds: float | None,
        ram_ceiling_mb: float,
        reaper_enabled: bool = True,
        pre_ping_on_acquire: bool = True,
    ) -> None:
        """:param spawn_fn: factory invoked once per (key) miss to create a server.
        :param idle_shutdown_seconds: how long an entry can sit at inflight=0
            before the reaper (T3) calls .stop() on it. If None, read
            O2_SCALPEL_LSP_IDLE_SHUTDOWN_SECONDS env var; default 600.0.
        :param ram_ceiling_mb: §16.1 hard ceiling; new spawn refused above this.
        :param reaper_enabled: whether to start the background reaper thread.
            Tests pass ``False`` to keep the per-test state deterministic.
        :param pre_ping_on_acquire: whether to health-probe cached entries
            before returning them. Tests may pass ``False`` to skip the probe.
        """
        import os as _os
        self._spawn_fn = spawn_fn
        if idle_shutdown_seconds is None:
            env = _os.environ.get("O2_SCALPEL_LSP_IDLE_SHUTDOWN_SECONDS")
            self._idle_seconds = float(env) if env is not None else 600.0
        else:
            self._idle_seconds = float(idle_shutdown_seconds)
        self._ram_ceiling_mb = ram_ceiling_mb
        self._reaper_enabled = reaper_enabled
        self._entries: OrderedDict[LspPoolKey, _ServerEntry] = OrderedDict()
        self._pool_lock = threading.Lock()
        self._spawn_count = 0
        self._pre_ping_fail_count = 0
        self._idle_reaped_count = 0
        self._budget_reject_count = 0
        self._reaper_event = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        self._pre_ping_on_acquire = pre_ping_on_acquire
        if reaper_enabled:
            self.start_reaper()

    # --- public API ------------------------------------------------------

    def acquire(self, key: LspPoolKey) -> Any:
        """Return the server for ``key``; spawn lazily on miss.

        When ``pre_ping_on_acquire`` is set, a cached entry is health-probed
        before being returned; on probe failure the entry is replaced
        transparently — the caller never sees a dead handle.
        """
        # First pass: cache hit?
        with self._pool_lock:
            entry = self._entries.get(key)
            had_entry = entry is not None and entry.server is not None
        if had_entry and self._pre_ping_on_acquire:
            if not self.pre_ping(key):
                # pre_ping has already popped the dead entry; fall through to
                # the spawn path below.
                pass
        # Second pass: locate-or-create + spawn-if-needed.
        with self._pool_lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _ServerEntry(server=None)
                self._entries[key] = entry
            entry.inflight += 1
            entry_lock = entry.entry_lock
        with entry_lock:
            if entry.server is None:
                try:
                    self._check_budget_or_raise(key)
                except WaitingForLspBudget:
                    with self._pool_lock:
                        # Roll back the inflight bump and pop the placeholder.
                        if entry.inflight > 0:
                            entry.inflight -= 1
                        if entry.server is None and entry.inflight == 0:
                            self._entries.pop(key, None)
                    raise
                log.info("LspPool spawn key=%s", key)
                entry.server = self._spawn_fn(key)
                self._spawn_count += 1
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

    def _check_budget_or_raise(self, key: LspPoolKey) -> None:
        rss = self._resident_set_size_mb()
        if rss > self._ram_ceiling_mb:
            with self._pool_lock:
                self._budget_reject_count += 1
            raise WaitingForLspBudget(
                f"LspPool spawn refused for key={key}: "
                f"{rss:.1f} MB > ceiling {self._ram_ceiling_mb:.1f} MB. "
                "Wait for idle shutdown to reclaim, or call pool.shutdown_all()."
            )

    def pre_ping(self, key: LspPoolKey) -> bool:
        """Cheap health probe: ``request_workspace_symbol("")``.

        Returns ``True`` if the server responded (any response counts; the
        empty-query result is fine). Returns ``False`` if the call raised or
        if no entry exists for ``key``. On failure, the dead entry is popped
        from the pool — the next ``acquire(key)`` re-spawns naturally.
        """
        with self._pool_lock:
            entry = self._entries.get(key)
        if entry is None or entry.server is None:
            return False
        try:
            entry.server.request_workspace_symbol("")
            return True
        except Exception:  # noqa: BLE001 — any failure means the child is dead.
            log.warning("LspPool pre_ping FAIL key=%s — replacing", key)
            with self._pool_lock:
                # Only pop if it's still the same entry (avoid racing a
                # concurrent reap or shutdown).
                cur = self._entries.get(key)
                if cur is entry:
                    self._entries.pop(key, None)
                self._pre_ping_fail_count += 1
            try:
                entry.server.stop()
            except Exception:  # pragma: no cover
                pass
            return False

    def pre_ping_all(self) -> dict[LspPoolKey, bool]:
        """Pre-ping every active entry. Returns a per-key result map."""
        with self._pool_lock:
            keys = list(self._entries.keys())
        return {k: self.pre_ping(k) for k in keys}

    def shutdown_all(self) -> None:
        """Stop every server and clear the pool. Idempotent."""
        self.stop_reaper()
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

    def start_reaper(self) -> None:
        """Spawn the daemon reaper thread. Idempotent."""
        if self._reaper_thread is not None and self._reaper_thread.is_alive():
            return
        self._reaper_event.clear()
        t = threading.Thread(target=self._reaper_loop, name="lsp-pool-reaper", daemon=True)
        self._reaper_thread = t
        t.start()

    def stop_reaper(self) -> None:
        """Signal the reaper to exit and join. Idempotent."""
        self._reaper_event.set()
        t = self._reaper_thread
        if t is not None:
            t.join(timeout=2.0)
        self._reaper_thread = None

    def _reaper_loop(self) -> None:
        # Tick at most every 60 s, and at least every idle_seconds/4 (so a
        # short test idle window still gets timely reaping).
        tick = max(0.01, min(60.0, self._idle_seconds / 4.0))
        while not self._reaper_event.wait(tick):
            try:
                self._reap_idle_once()
            except Exception:  # pragma: no cover
                log.exception("LspPool reaper tick raised")

    def _reap_idle_once(self) -> int:
        """Reap entries whose inflight==0 and last_used_ts is older than idle_seconds.

        Returns the count of entries reaped this tick.
        """
        now = self._now()
        # Phase 1: collect candidates under the pool lock; do not call stop()
        # while holding it (lock-order discipline mirrors Stage 1B
        # TransactionStore._evict_lru).
        candidates: list[_ServerEntry] = []
        with self._pool_lock:
            for key, entry in list(self._entries.items()):
                if entry.inflight == 0 and entry.server is not None and (now - entry.last_used_ts) >= self._idle_seconds:
                    candidates.append(entry)
                    # Remove eagerly so a concurrent acquire re-spawns rather
                    # than racing the reaper into stop().
                    self._entries.pop(key, None)
        # Phase 2: actually stop them.
        reaped = 0
        for entry in candidates:
            srv = entry.server
            if srv is None:
                continue
            try:
                srv.stop()
                reaped += 1
            except Exception:  # pragma: no cover
                log.exception("LspPool reap: stop() raised")
        if reaped:
            with self._pool_lock:
                self._idle_reaped_count += reaped
        return reaped

    # --- internals -------------------------------------------------------

    @staticmethod
    def _now() -> float:
        import time
        return time.monotonic()

    @staticmethod
    def _resident_set_size_mb() -> float:
        """Aggregate RSS of this Python process + spawned children, in MiB.

        Prefers ``psutil`` (cross-platform, recursive); degrades to POSIX
        ``resource.getrusage`` (RUSAGE_SELF + RUSAGE_CHILDREN). Per the
        no-new-runtime-deps rule, psutil is OPTIONAL — the fallback covers
        macOS + Linux which is the supported MVP host matrix.
        """
        try:
            import psutil  # type: ignore[import-not-found]
        except ImportError:
            psutil = None  # type: ignore[assignment]
        if psutil is not None:
            try:
                proc = psutil.Process()
                total_bytes = proc.memory_info().rss
                for child in proc.children(recursive=True):
                    try:
                        total_bytes += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                return total_bytes / (1024.0 * 1024.0)
            except Exception:  # pragma: no cover
                pass
        # POSIX fallback.
        import resource
        import sys
        self_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        kid_rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        total = float(self_rss + kid_rss)
        # ru_maxrss is kilobytes on Linux, bytes on macOS / BSD.
        divisor = 1024.0 if sys.platform == "linux" else 1024.0 * 1024.0
        return total / divisor
