"""T2 — LspPool skeleton: lazy spawn, acquire/release, per-key Lock."""

from __future__ import annotations

import threading
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from serena.refactoring.lsp_pool import LspPool, LspPoolKey


def test_acquire_spawns_lazily_on_first_call(slim_pool: LspPool, tmp_path) -> None:
    key = LspPoolKey(language="rust", project_root=str(tmp_path))
    assert slim_pool.stats().active_servers == 0
    srv = slim_pool.acquire(key)
    assert srv is not None
    assert slim_pool.stats().active_servers == 1


def test_second_acquire_returns_cached_instance(slim_pool: LspPool, tmp_path) -> None:
    key = LspPoolKey(language="rust", project_root=str(tmp_path))
    a = slim_pool.acquire(key)
    b = slim_pool.acquire(key)
    assert a is b
    assert slim_pool.stats().active_servers == 1


def test_distinct_keys_yield_distinct_servers(slim_pool: LspPool, tmp_path) -> None:
    k1 = LspPoolKey(language="rust", project_root=str(tmp_path))
    k2 = LspPoolKey(language="python", project_root=str(tmp_path))
    a = slim_pool.acquire(k1)
    b = slim_pool.acquire(k2)
    assert a is not b
    assert slim_pool.stats().active_servers == 2


def test_release_decrements_inflight_counter(slim_pool: LspPool, tmp_path) -> None:
    key = LspPoolKey(language="rust", project_root=str(tmp_path))
    slim_pool.acquire(key)
    slim_pool.acquire(key)
    assert slim_pool.stats().inflight[key] == 2
    slim_pool.release(key)
    assert slim_pool.stats().inflight[key] == 1
    slim_pool.release(key)
    assert slim_pool.stats().inflight[key] == 0


def test_release_unknown_key_is_noop(slim_pool: LspPool, tmp_path) -> None:
    key = LspPoolKey(language="rust", project_root=str(tmp_path))
    slim_pool.release(key)  # never acquired; must not raise.
    assert slim_pool.stats().active_servers == 0


def test_concurrent_acquire_for_same_key_shares_one_spawn(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    """Eight threads racing on the same key must call spawn_fn exactly once."""
    spawn_calls: list[LspPoolKey] = []
    spawn_lock = threading.Lock()

    def _spawn(key: LspPoolKey) -> MagicMock:
        with spawn_lock:
            spawn_calls.append(key)
        return fake_sls_factory(language=key.language, project_root=key.project_root)

    pool = LspPool(
        spawn_fn=_spawn,
        idle_shutdown_seconds=0.05,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        results: list[object] = []
        results_lock = threading.Lock()

        def _worker() -> None:
            srv = pool.acquire(key)
            with results_lock:
                results.append(srv)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(spawn_calls) == 1
        # All eight threads got the same instance.
        assert all(r is results[0] for r in results)
    finally:
        pool.shutdown_all()


def test_shutdown_all_stops_every_server(slim_pool: LspPool, tmp_path) -> None:
    k1 = LspPoolKey(language="rust", project_root=str(tmp_path))
    k2 = LspPoolKey(language="python", project_root=str(tmp_path))
    s1 = slim_pool.acquire(k1)
    s2 = slim_pool.acquire(k2)
    slim_pool.shutdown_all()
    s1.stop.assert_called()
    s2.stop.assert_called()
    assert slim_pool.stats().active_servers == 0
