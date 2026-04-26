"""T7 — Pool ↔ TransactionStore acquire-affinity."""

from __future__ import annotations

import time
from collections.abc import Callable
from unittest.mock import MagicMock

from serena.refactoring.lsp_pool import LspPool, LspPoolKey


def test_acquire_for_transaction_binds_key(
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
        srv = pool.acquire_for_transaction(key, transaction_id="txn-A")
        assert srv is not None
        # The same transaction acquiring again gets the same instance.
        again = pool.acquire_for_transaction(key, transaction_id="txn-A")
        assert again is srv
    finally:
        pool.shutdown_all()


def test_transaction_affinity_skips_pre_ping(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    """Even with crash_after_n_pings=0, an in-flight transaction never
    triggers a replacement spawn. The transaction owns the server until
    release_for_transaction is called.
    """
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language, crash_after_n_pings=0),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=True,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        first = pool.acquire_for_transaction(key, transaction_id="txn-X")
        # Even if the server would fail a probe, transaction acquires bypass it.
        second = pool.acquire_for_transaction(key, transaction_id="txn-X")
        assert first is second
        assert pool.stats().spawn_count == 1
        assert pool.stats().pre_ping_fail_count == 0
    finally:
        pool.shutdown_all()


def test_transaction_affinity_blocks_reaper(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    """A bound entry is exempt from idle reaping until released."""
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.01,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        srv = pool.acquire_for_transaction(key, transaction_id="txn-Y")
        # Sleep past idle window then reap; entry must survive.
        time.sleep(0.05)
        n = pool._reap_idle_once()
        assert n == 0
        srv.stop.assert_not_called()
    finally:
        pool.shutdown_all()


def test_release_for_transaction_re_enables_reaping(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.01,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        srv = pool.acquire_for_transaction(key, transaction_id="txn-Z")
        pool.release_for_transaction("txn-Z")
        time.sleep(0.05)
        n = pool._reap_idle_once()
        assert n == 1
        srv.stop.assert_called_once()
    finally:
        pool.shutdown_all()


def test_release_for_unknown_transaction_is_noop(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    try:
        pool.release_for_transaction("nonexistent")  # must not raise
    finally:
        pool.shutdown_all()


def test_two_transactions_can_share_one_server(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    """Affinity is additive — two transactions on the same key both pin the
    same entry; reaper-eligible only after BOTH release.
    """
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.01,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        a = pool.acquire_for_transaction(key, transaction_id="txn-1")
        b = pool.acquire_for_transaction(key, transaction_id="txn-2")
        assert a is b
        pool.release_for_transaction("txn-1")
        time.sleep(0.05)
        # Still pinned by txn-2:
        assert pool._reap_idle_once() == 0
        pool.release_for_transaction("txn-2")
        time.sleep(0.05)
        assert pool._reap_idle_once() == 1
    finally:
        pool.shutdown_all()
