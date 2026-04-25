"""T4 — pool_pre_ping health probe + spawn replacement on failure."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

from serena.refactoring.lsp_pool import LspPool, LspPoolKey


def test_pre_ping_returns_true_for_healthy_server(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        pool.acquire(key)
        assert pool.pre_ping(key) is True
        assert pool.stats().pre_ping_fail_count == 0
    finally:
        pool.shutdown_all()


def test_pre_ping_returns_false_for_dead_server_and_replaces(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language, crash_after_n_pings=0),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        first = pool.acquire(key)
        # crash_after_n_pings=0 → first ping raises.
        ok = pool.pre_ping(key)
        assert ok is False
        assert pool.stats().pre_ping_fail_count == 1
        # The dead entry must have been popped; next acquire spawns fresh.
        second = pool.acquire(key)
        assert second is not first
        assert pool.stats().spawn_count == 2
    finally:
        pool.shutdown_all()


def test_pre_ping_unknown_key_returns_false(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        assert pool.pre_ping(key) is False
    finally:
        pool.shutdown_all()


def test_acquire_with_pre_ping_on_acquire_replaces_dead(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    """When pre_ping_on_acquire=True (default), acquire detects a dead
    entry and replaces transparently — caller never sees the corpse."""
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language, crash_after_n_pings=0),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=True,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        first = pool.acquire(key)
        # Second acquire must pre-ping first (which crashes), then re-spawn.
        second = pool.acquire(key)
        assert second is not first
        assert pool.stats().spawn_count == 2
        assert pool.stats().pre_ping_fail_count == 1
    finally:
        pool.shutdown_all()


def test_pre_ping_all_walks_every_entry(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        keys = [
            LspPoolKey(language="rust", project_root="/tmp/a"),
            LspPoolKey(language="python", project_root="/tmp/b"),
        ]
        for k in keys:
            pool.acquire(k)
        results = pool.pre_ping_all()
        assert results == {keys[0]: True, keys[1]: True}
    finally:
        pool.shutdown_all()
