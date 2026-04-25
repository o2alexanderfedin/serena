"""T3 — idle-shutdown reaper + O2_SCALPEL_LSP_IDLE_SHUTDOWN_SECONDS env."""

from __future__ import annotations

import time
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from serena.refactoring.lsp_pool import LspPool, LspPoolKey


def test_idle_seconds_arg_takes_precedence_over_env(
    monkeypatch: pytest.MonkeyPatch,
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    monkeypatch.setenv("O2_SCALPEL_LSP_IDLE_SHUTDOWN_SECONDS", "999")
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.05,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    try:
        assert pool._idle_seconds == pytest.approx(0.05)
    finally:
        pool.shutdown_all()


def test_idle_seconds_arg_None_uses_env(
    monkeypatch: pytest.MonkeyPatch,
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    monkeypatch.setenv("O2_SCALPEL_LSP_IDLE_SHUTDOWN_SECONDS", "42")
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=None,  # type: ignore[arg-type]
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    try:
        assert pool._idle_seconds == pytest.approx(42.0)
    finally:
        pool.shutdown_all()


def test_idle_seconds_default_when_no_env(
    monkeypatch: pytest.MonkeyPatch,
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    monkeypatch.delenv("O2_SCALPEL_LSP_IDLE_SHUTDOWN_SECONDS", raising=False)
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=None,  # type: ignore[arg-type]
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    try:
        assert pool._idle_seconds == pytest.approx(600.0)
    finally:
        pool.shutdown_all()


def test_reap_idle_once_drops_idle_entry(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.01,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        srv = pool.acquire(key)
        pool.release(key)
        time.sleep(0.05)
        n = pool._reap_idle_once()
        assert n == 1
        srv.stop.assert_called_once()
        assert pool.stats().active_servers == 0
        assert pool.stats().idle_reaped_count == 1
    finally:
        pool.shutdown_all()


def test_reap_idle_once_skips_inflight_entry(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.01,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        srv = pool.acquire(key)  # inflight = 1; do NOT release.
        time.sleep(0.05)
        n = pool._reap_idle_once()
        assert n == 0
        srv.stop.assert_not_called()
    finally:
        pool.shutdown_all()


def test_acquire_after_reap_respawns(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.01,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        a = pool.acquire(key)
        pool.release(key)
        time.sleep(0.05)
        pool._reap_idle_once()
        b = pool.acquire(key)
        assert a is not b  # fresh spawn
        assert pool.stats().spawn_count == 2
    finally:
        pool.shutdown_all()


def test_reaper_thread_runs_in_background(
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.05,
        ram_ceiling_mb=4096.0,
        reaper_enabled=True,  # turn the reaper ON
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        srv = pool.acquire(key)
        pool.release(key)
        # Wait > 4× idle_seconds so the reaper tick fires at least once.
        time.sleep(0.5)
        srv.stop.assert_called()
        assert pool.stats().active_servers == 0
    finally:
        pool.shutdown_all()
