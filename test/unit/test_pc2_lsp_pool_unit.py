"""PC2 coverage uplift — serena.refactoring.lsp_pool uncovered ranges.

Target line ranges from Phase B coverage analysis:
  L123    acquire() → _acquire_internal
  L139    release() entry=None branch
  L154-163 release() entry present, inflight decrement
  L177-181 acquire_for_transaction() pin setup
  L186    acquire_for_transaction() internal path
  L190-203 release_for_transaction() unpin logic
  L210-221 _emit_event() with events_path configured
  L236    _acquire_internal: had_entry + pre_ping check
  L248-254 _acquire_internal: budget reject + inflight cleanup
  L268-271 _check_budget_or_raise: budget exceeded
  L285-303 pre_ping() success + failure paths
  L310-312 pre_ping_all()
  L344-349 start_reaper() idempotent + thread spawned
  L356    stop_reaper()
  L362-365 _reaper_loop tick
  L374-396 _reap_idle_once() candidates collected + stopped
  L399-404 _reap_idle_once() idle_reaped_count increment + event emit
  L424-425 _resident_set_size_mb() fallback path
  L433-434 _resident_set_size_mb() psutil path
  L439-443 _resident_set_size_mb() POSIX resource fallback

Pure unit tests using the slim_pool / fake_sls_factory fixtures from
test/spikes/conftest.py, plus inline fakes.
"""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring.lsp_pool import (
    LspPool,
    LspPoolKey,
    PoolStats,
    WaitingForLspBudget,
    _ServerEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_server(fail_ping: bool = False) -> MagicMock:
    """Minimal fake SolidLanguageServer for pool tests."""
    srv = MagicMock()
    if fail_ping:
        srv.request_workspace_symbol.side_effect = RuntimeError("dead server")
    else:
        srv.request_workspace_symbol.return_value = []
    srv.stop.return_value = None
    return srv


def _make_pool(
    *,
    capacity: int = 4096,
    reaper_enabled: bool = False,
    pre_ping: bool = False,
    events_path: Path | None = None,
    servers: dict[str, MagicMock] | None = None,
) -> tuple[LspPool, dict[str, MagicMock]]:
    """Create a pool backed by a registry of named fake servers."""
    if servers is None:
        servers = {}
    counter = [0]

    def _spawn(key: LspPoolKey) -> MagicMock:
        name = f"server-{key.language}-{counter[0]}"
        counter[0] += 1
        if key.language in servers:
            return servers[key.language]
        srv = _make_fake_server()
        servers[key.language] = srv
        return srv

    pool = LspPool(
        spawn_fn=_spawn,
        idle_shutdown_seconds=0.1,
        ram_ceiling_mb=float(capacity),
        reaper_enabled=reaper_enabled,
        pre_ping_on_acquire=pre_ping,
        events_path=events_path,
    )
    return pool, servers


# ---------------------------------------------------------------------------
# LspPoolKey canonicalisation
# ---------------------------------------------------------------------------


class TestLspPoolKey:
    def test_relative_path_resolved(self) -> None:
        k = LspPoolKey(language="rust", project_root=".")
        assert Path(k.project_root).is_absolute()

    def test_tilde_expanded(self) -> None:
        k = LspPoolKey(language="python", project_root="~/projects/myapp")
        assert "~" not in k.project_root

    def test_same_effective_path_same_key(self) -> None:
        home = str(Path.home())
        k1 = LspPoolKey(language="rust", project_root=home)
        k2 = LspPoolKey(language="rust", project_root="~")
        assert k1 == k2

    def test_different_languages_different_keys(self) -> None:
        k1 = LspPoolKey(language="rust", project_root="/tmp")
        k2 = LspPoolKey(language="python", project_root="/tmp")
        assert k1 != k2


# ---------------------------------------------------------------------------
# LspPool basic acquire / release
# ---------------------------------------------------------------------------


class TestLspPoolAcquireRelease:
    def test_acquire_spawns_on_first_miss(self) -> None:
        pool, servers = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/proj")
        srv = pool.acquire(key)
        assert srv is not None
        stats = pool.stats()
        assert stats.spawn_count == 1
        pool.shutdown_all()

    def test_acquire_returns_same_instance_on_hit(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/proj2")
        srv1 = pool.acquire(key)
        srv2 = pool.acquire(key)
        assert srv1 is srv2
        pool.shutdown_all()

    def test_release_decrements_inflight(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/proj3")
        pool.acquire(key)
        pool.acquire(key)
        pool.release(key)
        stats = pool.stats()
        assert stats.inflight[key] == 1
        pool.shutdown_all()

    def test_release_missing_key_does_not_raise(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/nonexistent")
        pool.release(key)  # should not raise
        pool.shutdown_all()

    def test_stats_active_servers(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="python", project_root="/tmp/proj4")
        pool.acquire(key)
        stats = pool.stats()
        assert stats.active_servers == 1
        pool.shutdown_all()


# ---------------------------------------------------------------------------
# LspPool.acquire_for_transaction / release_for_transaction
# ---------------------------------------------------------------------------


class TestLspPoolTransactionPinning:
    def test_acquire_for_transaction_returns_server(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/txn1")
        srv = pool.acquire_for_transaction(key, "txn-abc")
        assert srv is not None
        pool.shutdown_all()

    def test_second_acquire_same_txn_same_key_returns_same_server(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/txn2")
        srv1 = pool.acquire_for_transaction(key, "txn-xyz")
        srv2 = pool.acquire_for_transaction(key, "txn-xyz")
        assert srv1 is srv2
        pool.shutdown_all()

    def test_release_for_transaction_clears_pin(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/txn3")
        pool.acquire_for_transaction(key, "txn-1")
        pool.release_for_transaction("txn-1")
        # Pin should be gone from internal dicts.
        with pool._pool_lock:
            assert "txn-1" not in pool._txn_pins
        pool.shutdown_all()

    def test_release_for_transaction_unknown_txn_is_noop(self) -> None:
        pool, _ = _make_pool()
        pool.release_for_transaction("nonexistent-txn")  # must not raise
        pool.shutdown_all()

    def test_multi_transaction_pin_ref_count(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/txn4")
        pool.acquire_for_transaction(key, "txn-A")
        pool.acquire_for_transaction(key, "txn-B")
        pool.release_for_transaction("txn-A")
        # txn-B still has the pin.
        with pool._pool_lock:
            assert key in pool._pinned_keys
        pool.release_for_transaction("txn-B")
        with pool._pool_lock:
            assert key not in pool._pinned_keys
        pool.shutdown_all()


# ---------------------------------------------------------------------------
# LspPool.pre_ping / pre_ping_all
# ---------------------------------------------------------------------------


class TestLspPoolPrePing:
    def test_pre_ping_healthy_server_returns_true(self) -> None:
        fake_srv = _make_fake_server(fail_ping=False)
        pool, _ = _make_pool(servers={"rust": fake_srv})
        key = LspPoolKey(language="rust", project_root="/tmp/ping1")
        pool.acquire(key)
        result = pool.pre_ping(key)
        assert result is True
        pool.shutdown_all()

    def test_pre_ping_dead_server_returns_false_and_evicts(self) -> None:
        fake_srv = _make_fake_server(fail_ping=True)
        pool, _ = _make_pool(servers={"rust": fake_srv})
        key = LspPoolKey(language="rust", project_root="/tmp/ping2")
        pool.acquire(key)
        result = pool.pre_ping(key)
        assert result is False
        # Entry evicted from pool.
        with pool._pool_lock:
            assert key not in pool._entries
        pool.shutdown_all()

    def test_pre_ping_absent_key_returns_false(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/ping3")
        result = pool.pre_ping(key)
        assert result is False
        pool.shutdown_all()

    def test_pre_ping_all_returns_per_key_map(self) -> None:
        pool, _ = _make_pool()
        key1 = LspPoolKey(language="rust", project_root="/tmp/all1")
        key2 = LspPoolKey(language="python", project_root="/tmp/all2")
        pool.acquire(key1)
        pool.acquire(key2)
        results = pool.pre_ping_all()
        assert key1 in results
        assert key2 in results
        pool.shutdown_all()


# ---------------------------------------------------------------------------
# LspPool budget enforcement
# ---------------------------------------------------------------------------


class TestLspPoolBudget:
    def test_budget_exceeded_raises_waiting_for_lsp_budget(self) -> None:
        # Set ceiling so low that any real RSS exceeds it.
        pool = LspPool(
            spawn_fn=lambda key: _make_fake_server(),
            idle_shutdown_seconds=600.0,
            ram_ceiling_mb=0.001,  # absurdly low
            reaper_enabled=False,
        )
        key = LspPoolKey(language="rust", project_root="/tmp/budget1")
        with pytest.raises(WaitingForLspBudget):
            pool.acquire(key)
        stats = pool.stats()
        assert stats.budget_reject_count >= 1
        pool.shutdown_all()


# ---------------------------------------------------------------------------
# LspPool.shutdown_all
# ---------------------------------------------------------------------------


class TestLspPoolShutdownAll:
    def test_shutdown_all_clears_pool(self) -> None:
        pool, _ = _make_pool()
        key = LspPoolKey(language="rust", project_root="/tmp/shut1")
        pool.acquire(key)
        pool.shutdown_all()
        stats = pool.stats()
        assert stats.active_servers == 0

    def test_shutdown_all_idempotent(self) -> None:
        pool, _ = _make_pool()
        pool.shutdown_all()
        pool.shutdown_all()  # Should not raise.


# ---------------------------------------------------------------------------
# LspPool reaper thread
# ---------------------------------------------------------------------------


class TestLspPoolReaper:
    def test_start_reaper_spawns_thread(self) -> None:
        pool = LspPool(
            spawn_fn=lambda key: _make_fake_server(),
            idle_shutdown_seconds=60.0,
            ram_ceiling_mb=4096.0,
            reaper_enabled=False,  # Don't start automatically.
        )
        assert pool._reaper_thread is None
        pool.start_reaper()
        assert pool._reaper_thread is not None
        assert pool._reaper_thread.is_alive()
        pool.shutdown_all()

    def test_start_reaper_idempotent(self) -> None:
        pool = LspPool(
            spawn_fn=lambda key: _make_fake_server(),
            idle_shutdown_seconds=60.0,
            ram_ceiling_mb=4096.0,
            reaper_enabled=False,
        )
        pool.start_reaper()
        t1 = pool._reaper_thread
        pool.start_reaper()  # second call — same thread.
        assert pool._reaper_thread is t1
        pool.shutdown_all()

    def test_reap_idle_once_reaps_eligible_entry(self) -> None:
        pool = LspPool(
            spawn_fn=lambda key: _make_fake_server(),
            idle_shutdown_seconds=0.01,  # very short idle window
            ram_ceiling_mb=4096.0,
            reaper_enabled=False,
        )
        key = LspPoolKey(language="rust", project_root="/tmp/reap1")
        pool.acquire(key)
        pool.release(key)  # inflight = 0
        # Force last_used_ts to be old.
        with pool._pool_lock:
            entry = pool._entries.get(key)
            if entry is not None:
                entry.last_used_ts = pool._now() - 10.0

        reaped = pool._reap_idle_once()
        assert reaped == 1
        assert pool.stats().idle_reaped_count == 1
        pool.shutdown_all()

    def test_reap_idle_skips_pinned_entries(self) -> None:
        pool = LspPool(
            spawn_fn=lambda key: _make_fake_server(),
            idle_shutdown_seconds=0.01,
            ram_ceiling_mb=4096.0,
            reaper_enabled=False,
        )
        key = LspPoolKey(language="rust", project_root="/tmp/reap2")
        pool.acquire_for_transaction(key, "active-txn")
        # Force last_used_ts to be old.
        with pool._pool_lock:
            entry = pool._entries.get(key)
            if entry is not None:
                entry.last_used_ts = pool._now() - 10.0

        reaped = pool._reap_idle_once()
        assert reaped == 0  # Pinned entry not reaped.
        pool.release_for_transaction("active-txn")
        pool.shutdown_all()


# ---------------------------------------------------------------------------
# LspPool telemetry events
# ---------------------------------------------------------------------------


class TestLspPoolTelemetryEvents:
    def test_events_written_on_acquire(self, tmp_path: Path) -> None:
        events_path = tmp_path / "pool-events.jsonl"
        pool, _ = _make_pool(events_path=events_path)
        key = LspPoolKey(language="rust", project_root="/tmp/events1")
        pool.acquire(key)
        pool.shutdown_all()
        assert events_path.exists()
        lines = events_path.read_text().splitlines()
        kinds = {__import__("json").loads(l)["kind"] for l in lines if l}
        assert "acquire" in kinds or "spawn" in kinds

    def test_events_written_on_release(self, tmp_path: Path) -> None:
        events_path = tmp_path / "pool-events2.jsonl"
        pool, _ = _make_pool(events_path=events_path)
        key = LspPoolKey(language="python", project_root="/tmp/events2")
        pool.acquire(key)
        pool.release(key)
        pool.shutdown_all()
        lines = events_path.read_text().splitlines()
        kinds = [__import__("json").loads(l)["kind"] for l in lines if l]
        assert "release" in kinds


# ---------------------------------------------------------------------------
# LspPool._resident_set_size_mb (coverage of both code paths)
# ---------------------------------------------------------------------------


class TestResidentSetSizeMb:
    def test_returns_positive_float(self) -> None:
        result = LspPool._resident_set_size_mb()
        assert isinstance(result, float)
        assert result > 0.0

    def test_psutil_path_used_when_available(self) -> None:
        """If psutil is importable, the psutil branch is taken."""
        try:
            import psutil  # noqa: F401
            result = LspPool._resident_set_size_mb()
            assert result > 0.0
        except ImportError:
            pytest.skip("psutil not installed")

    def test_resource_fallback_when_psutil_missing(self) -> None:
        """Simulate psutil ImportError; resource fallback should run."""
        import sys
        original = sys.modules.get("psutil")
        try:
            # Temporarily hide psutil.
            sys.modules["psutil"] = None  # type: ignore[assignment]
            result = LspPool._resident_set_size_mb()
            assert isinstance(result, float)
        finally:
            if original is not None:
                sys.modules["psutil"] = original
            else:
                sys.modules.pop("psutil", None)
