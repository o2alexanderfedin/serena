"""T2 — broadcast() parallel fan-out + timeout / error collection."""

from __future__ import annotations

import pytest

from serena.refactoring.multi_server import (
    MultiServerBroadcastResult,
    MultiServerCoordinator,
)


@pytest.mark.asyncio
async def test_broadcast_all_success(fake_pool):
    fake_pool["pylsp-rope"].code_actions = [{"title": "rope", "kind": "refactor.extract"}]
    fake_pool["basedpyright"].code_actions = [{"title": "bp", "kind": "quickfix"}]
    fake_pool["ruff"].code_actions = [{"title": "ruff", "kind": "source.fixAll.ruff"}]
    coord = MultiServerCoordinator(fake_pool)
    result = await coord.broadcast(
        method="textDocument/codeAction",
        kwargs={
            "file": "/tmp/x.py",
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        },
        timeout_ms=2000,
    )
    assert isinstance(result, MultiServerBroadcastResult)
    assert set(result.responses.keys()) == {"pylsp-rope", "basedpyright", "ruff"}
    assert result.timeouts == []
    assert result.errors == {}


@pytest.mark.asyncio
async def test_broadcast_one_timeout(fake_pool):
    fake_pool["pylsp-rope"].sleep_ms = 500  # exceeds 100ms timeout
    fake_pool["basedpyright"].code_actions = [{"title": "bp", "kind": "quickfix"}]
    fake_pool["ruff"].code_actions = [{"title": "ruff", "kind": "source.fixAll.ruff"}]
    coord = MultiServerCoordinator(fake_pool)
    result = await coord.broadcast(
        method="textDocument/codeAction",
        kwargs={
            "file": "/tmp/x.py",
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        },
        timeout_ms=100,
    )
    assert "pylsp-rope" not in result.responses
    assert {w.server for w in result.timeouts} == {"pylsp-rope"}
    assert result.timeouts[0].method == "textDocument/codeAction"
    assert result.timeouts[0].timeout_ms == 100
    assert result.timeouts[0].after_ms >= 100
    assert set(result.responses.keys()) == {"basedpyright", "ruff"}


@pytest.mark.asyncio
async def test_broadcast_one_error(fake_pool):
    fake_pool["pylsp-rope"].code_actions = [{"title": "rope", "kind": "refactor"}]
    fake_pool["basedpyright"].raises = RuntimeError
    fake_pool["ruff"].code_actions = [{"title": "ruff", "kind": "source.fixAll.ruff"}]
    coord = MultiServerCoordinator(fake_pool)
    result = await coord.broadcast(
        method="textDocument/codeAction",
        kwargs={
            "file": "/tmp/x.py",
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        },
        timeout_ms=2000,
    )
    assert "basedpyright" not in result.responses
    assert "basedpyright" in result.errors
    assert "raised" in result.errors["basedpyright"]
    assert set(result.responses.keys()) == {"pylsp-rope", "ruff"}


@pytest.mark.asyncio
async def test_broadcast_env_default_timeout_2000ms(fake_pool, monkeypatch):
    """When timeout_ms is omitted, default reads from
    O2_SCALPEL_BROADCAST_TIMEOUT_MS or falls back to 2000."""
    monkeypatch.setenv("O2_SCALPEL_BROADCAST_TIMEOUT_MS", "50")
    fake_pool["pylsp-rope"].sleep_ms = 200
    coord = MultiServerCoordinator(fake_pool)
    result = await coord.broadcast(
        method="textDocument/codeAction",
        kwargs={
            "file": "/tmp/x.py",
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 0},
        },
    )
    assert result.timeouts and result.timeouts[0].timeout_ms == 50


@pytest.mark.asyncio
async def test_broadcast_unknown_method_raises_value_error(fake_pool):
    coord = MultiServerCoordinator(fake_pool)
    with pytest.raises(ValueError, match="unsupported broadcast method"):
        await coord.broadcast(method="textDocument/notARealLspMethod", kwargs={})
