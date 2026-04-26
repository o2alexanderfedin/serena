"""T8 — telemetry: .serena/pool-events.jsonl emission."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from serena.refactoring.lsp_pool import LspPool, LspPoolKey, WaitingForLspBudget


def _read_events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_spawn_emits_event(
    tmp_path: Path, fake_sls_factory: Callable[..., MagicMock],
) -> None:
    events_path = tmp_path / ".serena" / "pool-events.jsonl"
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
        events_path=events_path,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        pool.acquire(key)
        events = _read_events(events_path)
        kinds = [e["kind"] for e in events]
        assert "spawn" in kinds
        assert "acquire" in kinds
        spawn_evt = next(e for e in events if e["kind"] == "spawn")
        assert spawn_evt["language"] == "rust"
    finally:
        pool.shutdown_all()


def test_release_emits_event(
    tmp_path: Path, fake_sls_factory: Callable[..., MagicMock],
) -> None:
    events_path = tmp_path / ".serena" / "pool-events.jsonl"
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
        events_path=events_path,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        pool.acquire(key)
        pool.release(key)
        events = _read_events(events_path)
        assert any(e["kind"] == "release" for e in events)
    finally:
        pool.shutdown_all()


def test_pre_ping_fail_emits_event(
    tmp_path: Path, fake_sls_factory: Callable[..., MagicMock],
) -> None:
    events_path = tmp_path / ".serena" / "pool-events.jsonl"
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language, crash_after_n_pings=0),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
        events_path=events_path,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        pool.acquire(key)
        pool.pre_ping(key)
        events = _read_events(events_path)
        assert any(e["kind"] == "pre_ping_fail" for e in events)
    finally:
        pool.shutdown_all()


def test_idle_reap_emits_event(
    tmp_path: Path, fake_sls_factory: Callable[..., MagicMock],
) -> None:
    events_path = tmp_path / ".serena" / "pool-events.jsonl"
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=0.01,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
        events_path=events_path,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        pool.acquire(key)
        pool.release(key)
        time.sleep(0.05)
        pool._reap_idle_once()
        events = _read_events(events_path)
        assert any(e["kind"] == "idle_reap" for e in events)
    finally:
        pool.shutdown_all()


def test_budget_reject_emits_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    fake_sls_factory: Callable[..., MagicMock],
) -> None:
    events_path = tmp_path / ".serena" / "pool-events.jsonl"
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
        events_path=events_path,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        with pytest.raises(WaitingForLspBudget):
            pool.acquire(key)
        events = _read_events(events_path)
        assert any(e["kind"] == "budget_reject" for e in events)
    finally:
        pool.shutdown_all()


def test_no_events_path_silently_skips_write(
    tmp_path: Path, fake_sls_factory: Callable[..., MagicMock],
) -> None:
    """When events_path=None the pool emits nothing to disk (default for tests
    that don't care about telemetry)."""
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
        events_path=None,
    )
    try:
        key = LspPoolKey(language="rust", project_root="/tmp")
        pool.acquire(key)
        # No file should appear under the test's tmp_path:
        assert not (tmp_path / ".serena").exists()
    finally:
        pool.shutdown_all()


def test_events_directory_is_created_on_demand(
    tmp_path: Path, fake_sls_factory: Callable[..., MagicMock],
) -> None:
    events_path = tmp_path / "deep" / "subdir" / "pool-events.jsonl"
    pool = LspPool(
        spawn_fn=lambda k: fake_sls_factory(language=k.language),
        idle_shutdown_seconds=600.0,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
        pre_ping_on_acquire=False,
        events_path=events_path,
    )
    try:
        pool.acquire(LspPoolKey(language="rust", project_root="/tmp"))
        assert events_path.exists()
    finally:
        pool.shutdown_all()
