"""T5 — RAM-budget guard + WaitingForLspBudget error."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from serena.refactoring.lsp_pool import LspPool, LspPoolKey, WaitingForLspBudget


def test_acquire_under_budget_succeeds(
    fake_sls_factory: Callable[..., MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "serena.refactoring.lsp_pool.LspPool._resident_set_size_mb",
        staticmethod(lambda: 100.0),
    )
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=8192.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        srv = pool.acquire(key)
        assert srv is not None
        assert pool.stats().budget_reject_count == 0
    finally:
        pool.shutdown_all()


def test_acquire_over_budget_raises_WaitingForLspBudget(
    fake_sls_factory: Callable[..., MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "serena.refactoring.lsp_pool.LspPool._resident_set_size_mb",
        staticmethod(lambda: 9999.0),
    )
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=8192.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        with pytest.raises(WaitingForLspBudget) as excinfo:
            pool.acquire(key)
        assert "8192" in str(excinfo.value)
        assert "9999" in str(excinfo.value)
        assert pool.stats().budget_reject_count == 1
        assert pool.stats().active_servers == 0
    finally:
        pool.shutdown_all()


def test_cache_hit_skips_budget_check(
    fake_sls_factory: Callable[..., MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already-spawned entry is reachable even if RSS is now over budget;
    the guard only blocks NEW spawns."""
    rss_box = {"v": 100.0}
    monkeypatch.setattr(
        "serena.refactoring.lsp_pool.LspPool._resident_set_size_mb",
        staticmethod(lambda: rss_box["v"]),
    )
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=8192.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        first = pool.acquire(key)
        rss_box["v"] = 9999.0  # blow the budget
        again = pool.acquire(key)  # cache hit; must succeed
        assert again is first
        assert pool.stats().budget_reject_count == 0
    finally:
        pool.shutdown_all()


def test_resident_set_size_mb_returns_positive_number_on_this_host() -> None:
    """Smoke test: the helper returns a finite positive number on every
    supported platform (psutil happy path or POSIX fallback)."""
    from serena.refactoring.lsp_pool import LspPool
    rss = LspPool._resident_set_size_mb()
    assert rss > 0.0
    assert rss < 1_000_000.0  # 1 TB is an absurd upper bound
