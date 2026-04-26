"""T0 — smoke test the _FakeServer fixture so downstream tasks rely on it safely."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_fake_pool_three_servers(fake_pool):
    assert set(fake_pool.keys()) == {"pylsp-rope", "basedpyright", "ruff"}
    for sid, srv in fake_pool.items():
        assert srv.server_id == sid


@pytest.mark.asyncio
async def test_fake_request_code_actions_filters_by_only_prefix(fake_pool):
    srv = fake_pool["ruff"]
    srv.code_actions = [
        {"title": "Organize imports (ruff)", "kind": "source.organizeImports.ruff"},
        {"title": "Fix all (ruff)", "kind": "source.fixAll.ruff"},
        {"title": "Quickfix", "kind": "quickfix"},
    ]
    out = await srv.request_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["source.organizeImports"],
    )
    assert len(out) == 1
    assert out[0]["kind"] == "source.organizeImports.ruff"


@pytest.mark.asyncio
async def test_fake_timeout_via_sleep_ms(fake_pool):
    import asyncio
    srv = fake_pool["pylsp-rope"]
    srv.sleep_ms = 200
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            srv.request_code_actions("/tmp/x.py", {"line": 0, "character": 0}, {"line": 0, "character": 0}),
            timeout=0.05,
        )


@pytest.mark.asyncio
async def test_fake_raises_propagates(fake_pool):
    srv = fake_pool["basedpyright"]
    srv.raises = RuntimeError
    with pytest.raises(RuntimeError):
        await srv.request_code_actions("/tmp/x.py", {"line": 0, "character": 0}, {"line": 0, "character": 0})
