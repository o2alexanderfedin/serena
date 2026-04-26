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

from pydantic import BaseModel

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


class PoolEvent(BaseModel):
    """One JSONL row emitted to ``.serena/pool-events.jsonl``."""

    ts: float
    kind: str  # spawn / acquire / release / pre_ping_fail / idle_reap / budget_reject
    language: str | None = None
    project_root: str | None = None
    inflight: int | None = None
    rss_mb: float | None = None
    ceiling_mb: float | None = None
    transaction_id: str | None = None


class LspPool:
    """In-memory pool of ``SolidLanguageServer`` instances keyed by ``LspPoolKey``."""

    def __init__(
        self,
        spawn_fn: Callable[[LspPoolKey], Any],
        idle_shutdown_seconds: float | None,
        ram_ceiling_mb: float,
        reaper_enabled: bool = True,
        pre_ping_on_acquire: bool = True,
        events_path: Path | None = None,
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
        :param events_path: path to JSONL file for telemetry events. If None,
            no events are emitted (default for tests that don't care).
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
        self._txn_pins: dict[str, set[LspPoolKey]] = {}
        self._pinned_keys: dict[LspPoolKey, int] = {}
        self._events_path = events_path
        if reaper_enabled:
            self.start_reaper()

    # --- public API ------------------------------------------------------

    def acquire(self, key: LspPoolKey) -> Any:
        """Return the server for ``key``; spawn lazily on miss.

        When ``pre_ping_on_acquire`` is set, a cached entry is health-probed
        before being returned; on probe failure the entry is replaced
        transparently — the caller never sees a dead handle.
        """
        return self._acquire_internal(key, allow_pre_ping=True)

    def release(self, key: LspPoolKey) -> None:
        """Decrement the in-flight counter for ``key``; reaper-eligible at 0."""
        with self._pool_lock:
            entry = self._entries.get(key)
            if entry is None:
                inflight_count = 0
            else:
                if entry.inflight > 0:
                    entry.inflight -= 1
                entry.last_used_ts = self._now()
                inflight_count = entry.inflight
        self._emit_event("release", key=key, inflight=inflight_count)

    def acquire_for_transaction(self, key: LspPoolKey, transaction_id: str) -> Any:
        """Acquire ``key`` AND pin the entry to ``transaction_id``.

        The pin guarantees:
        - subsequent ``acquire_for_transaction(same key, same tid)`` returns
          the same instance (no pre-ping replacement);
        - the reaper skips this entry until ``release_for_transaction(tid)``
          is called.

        Multiple transactions can pin the same key; the entry is reaper-eligible
        only after every pin is released.
        """
        with self._pool_lock:
            self._txn_pins.setdefault(transaction_id, set())
            if key not in self._txn_pins[transaction_id]:
                self._txn_pins[transaction_id].add(key)
                self._pinned_keys[key] = self._pinned_keys.get(key, 0) + 1
        # Reuse the regular acquire path BUT bypass pre_ping when the entry is
        # already pinned (the second-and-later acquire on the same tid).
        # Implementation: temporarily flip pre_ping_on_acquire off for this
        # call. Cleaner: route through an internal helper.
        return self._acquire_internal(key, allow_pre_ping=False)

    def release_for_transaction(self, transaction_id: str) -> None:
        """Drop the transaction's pins; reaper becomes eligible to take them."""
        with self._pool_lock:
            keys = self._txn_pins.pop(transaction_id, set())
            for k in keys:
                # Decrement inflight (acquired via acquire_for_transaction).
                entry = self._entries.get(k)
                if entry is not None and entry.inflight > 0:
                    entry.inflight -= 1
                    entry.last_used_ts = self._now()
                # Decrement pin count.
                n = self._pinned_keys.get(k, 0) - 1
                if n <= 0:
                    self._pinned_keys.pop(k, None)
                else:
                    self._pinned_keys[k] = n

    # ----------------------------------------------------------------------

    def _emit_event(self, kind: str, key: LspPoolKey | None = None, **fields: object) -> None:
        if self._events_path is None:
            return
        try:
            evt = PoolEvent(
                ts=self._now(),
                kind=kind,
                language=key.language if key is not None else None,
                project_root=key.project_root if key is not None else None,
                **fields,  # type: ignore[arg-type]
            )
            self._events_path.parent.mkdir(parents=True, exist_ok=True)
            with self._events_path.open("a", encoding="utf-8") as f:
                f.write(evt.model_dump_json())
                f.write("\n")
        except Exception:  # pragma: no cover — telemetry is best-effort
            log.exception("LspPool telemetry emit failed (kind=%s)", kind)

    def _acquire_internal(self, key: LspPoolKey, allow_pre_ping: bool) -> Any:
        """Like ``acquire`` but with explicit pre-ping toggle.

        ``acquire`` is a thin wrapper that sets ``allow_pre_ping`` from the
        ctor flag. ``acquire_for_transaction`` calls this with False so the
        bound transaction never sees a replacement.
        """
        with self._pool_lock:
            entry = self._entries.get(key)
            had_entry = entry is not None and entry.server is not None
        if had_entry and allow_pre_ping and self._pre_ping_on_acquire:
            self.pre_ping(key)
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
                        if entry.inflight > 0:
                            entry.inflight -= 1
                        if entry.server is None and entry.inflight == 0:
                            self._entries.pop(key, None)
                    raise
                log.info("LspPool spawn key=%s", key)
                entry.server = self._spawn_fn(key)
                self._spawn_count += 1
                self._emit_event("spawn", key=key)
        with self._pool_lock:
            entry.last_used_ts = self._now()
            self._entries.move_to_end(key)
        self._emit_event("acquire", key=key, inflight=entry.inflight)
        return entry.server

    def _check_budget_or_raise(self, key: LspPoolKey) -> None:
        rss = self._resident_set_size_mb()
        if rss > self._ram_ceiling_mb:
            with self._pool_lock:
                self._budget_reject_count += 1
            self._emit_event("budget_reject", key=key, rss_mb=rss, ceiling_mb=self._ram_ceiling_mb)
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
            self._emit_event("pre_ping_fail", key=key)
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
        candidates: list[tuple[LspPoolKey, _ServerEntry]] = []
        with self._pool_lock:
            for key, entry in list(self._entries.items()):
                if key in self._pinned_keys:
                    continue  # transaction-pinned: exempt from reap.
                if entry.inflight == 0 and entry.server is not None and (now - entry.last_used_ts) >= self._idle_seconds:
                    candidates.append((key, entry))
                    # Remove eagerly so a concurrent acquire re-spawns rather
                    # than racing the reaper into stop().
                    self._entries.pop(key, None)
        # Phase 2: actually stop them.
        reaped = 0
        for _, entry in candidates:
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
            for k, _ in candidates:
                self._emit_event("idle_reap", key=k)
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
