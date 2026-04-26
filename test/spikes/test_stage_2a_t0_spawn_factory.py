"""Stage 2A T1 — real solidlsp spawn factory.

Replaces ScalpelRuntime._default_spawn_fn's NotImplementedError with
a real factory that dispatches by LspPoolKey.language string tag to the
four Stage 1E adapter classes.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from serena.refactoring.lsp_pool import LspPoolKey
from serena.tools.scalpel_runtime import (
    _SPAWN_DISPATCH_TABLE,
    _AsyncAdapter,
    _default_spawn_fn,
    parse_workspace_extra_paths,
)


def test_dispatch_table_lists_exactly_four_tags():
    assert set(_SPAWN_DISPATCH_TABLE.keys()) == {
        "rust",
        "python:pylsp-rope",
        "python:basedpyright",
        "python:ruff",
    }


def test_unknown_tag_raises_with_structured_message(tmp_path):
    key = LspPoolKey(language="ocaml", project_root=str(tmp_path))
    with pytest.raises(ValueError) as exc:
        _default_spawn_fn(key)
    msg = str(exc.value)
    assert "ocaml" in msg
    for valid in ("rust", "python:pylsp-rope", "python:basedpyright", "python:ruff"):
        assert valid in msg


def test_rust_tag_dispatches_to_rust_analyzer(tmp_path):
    key = LspPoolKey(language="rust", project_root=str(tmp_path))
    with patch(
        "solidlsp.language_servers.rust_analyzer.RustAnalyzer"
    ) as mock_cls:
        mock_cls.return_value = "synthetic-server"
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner == "synthetic-server"
    assert mock_cls.called
    call_kwargs = mock_cls.call_args.kwargs or {}
    call_args = mock_cls.call_args.args
    config = call_kwargs.get("config") if "config" in call_kwargs else call_args[0]
    assert config.code_language.value == "rust"


def test_python_pylsp_rope_tag_dispatches_to_pylsp_server(tmp_path):
    key = LspPoolKey(
        language="python:pylsp-rope", project_root=str(tmp_path),
    )
    with patch(
        "solidlsp.language_servers.pylsp_server.PylspServer"
    ) as mock_cls:
        mock_cls.return_value = "fake-pylsp"
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner == "fake-pylsp"
    assert mock_cls.called


def test_python_basedpyright_tag_dispatches_to_basedpyright_server(tmp_path):
    key = LspPoolKey(
        language="python:basedpyright", project_root=str(tmp_path),
    )
    with patch(
        "solidlsp.language_servers.basedpyright_server.BasedpyrightServer"
    ) as mock_cls:
        mock_cls.return_value = "fake-bp"
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner == "fake-bp"


def test_python_ruff_tag_dispatches_to_ruff_server(tmp_path):
    key = LspPoolKey(
        language="python:ruff", project_root=str(tmp_path),
    )
    with patch(
        "solidlsp.language_servers.ruff_server.RuffServer"
    ) as mock_cls:
        mock_cls.return_value = "fake-ruff"
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner == "fake-ruff"


def test_async_adapter_wraps_sync_facade_methods_into_coroutines():
    """Verify the _AsyncAdapter pattern that fixes the sync/async wrapping gap.

    Stage 1H surfaced: MultiServerCoordinator.broadcast does
    `await getattr(server, facade_name)(**kwargs)`. Real Stage 1E adapters
    are sync, so this would raise TypeError. The _AsyncAdapter wraps the
    four facade methods so they return coroutines.
    """
    import asyncio

    class _SyncStub:
        def request_code_actions(self, **kwargs):
            return ["sync-result"]

        def some_other_method(self):
            return "passthrough"

    adapter = _AsyncAdapter(_SyncStub())
    # Wrapped facade methods return coroutines.
    coro = adapter.request_code_actions(file="x", start={}, end={})
    assert asyncio.iscoroutine(coro)
    result = asyncio.run(coro)
    assert result == ["sync-result"]
    # Non-facade attributes pass through unchanged (still sync).
    assert adapter.some_other_method() == "passthrough"


def test_parse_workspace_extra_paths_empty_when_unset(monkeypatch):
    monkeypatch.delenv("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", raising=False)
    assert parse_workspace_extra_paths() == ()


def test_parse_workspace_extra_paths_splits_on_pathsep(monkeypatch, tmp_path):
    p1 = tmp_path / "a"
    p2 = tmp_path / "b"
    p1.mkdir()
    p2.mkdir()
    monkeypatch.setenv(
        "O2_SCALPEL_WORKSPACE_EXTRA_PATHS",
        f"{p1}{os.pathsep}{p2}",
    )
    out = parse_workspace_extra_paths()
    assert tuple(sorted(out)) == tuple(sorted((str(p1), str(p2))))


def test_parse_workspace_extra_paths_skips_blank_entries(monkeypatch, tmp_path):
    p1 = tmp_path / "a"
    p1.mkdir()
    monkeypatch.setenv(
        "O2_SCALPEL_WORKSPACE_EXTRA_PATHS",
        f"{os.pathsep}{p1}{os.pathsep}{os.pathsep}",
    )
    assert parse_workspace_extra_paths() == (str(p1),)
