"""Stage 2A T1 — real solidlsp spawn factory.

Replaces ScalpelRuntime._default_spawn_fn's NotImplementedError with
a real factory that dispatches by LspPoolKey.language string tag to the
four Stage 1E adapter classes.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring.lsp_pool import LspPoolKey
from serena.tools.scalpel_runtime import (
    _SPAWN_DISPATCH_TABLE,
    _AsyncAdapter,
    _default_spawn_fn,
    parse_workspace_extra_paths,
)


def test_dispatch_table_lists_exactly_five_tags():
    """v1.1.1 Leaf 02 — markdown joins as the fifth language tag.

    The four production-Python + Rust tags stay; the new ``markdown``
    entry routes ``MarkdownStrategy.build_servers`` (single-LSP) to
    ``MarksmanLanguageServer`` via the same ``_AsyncAdapter`` wrapping.
    """
    assert set(_SPAWN_DISPATCH_TABLE.keys()) == {
        "rust",
        "python:pylsp-rope",
        "python:basedpyright",
        "python:ruff",
        "markdown",
    }


def test_markdown_tag_dispatches_to_marksman_language_server(tmp_path):
    """v1.1.1 Leaf 02 — ``markdown`` resolves to MarksmanLanguageServer."""
    key = LspPoolKey(language="markdown", project_root=str(tmp_path))
    fake_server = MagicMock(name="marksman-instance")
    with patch(
        "solidlsp.language_servers.marksman_server.MarksmanLanguageServer"
    ) as mock_cls:
        mock_cls.return_value = fake_server
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner is fake_server
    assert mock_cls.called
    fake_server.start.assert_called_once()


def test_unknown_tag_raises_with_structured_message(tmp_path):
    key = LspPoolKey(language="ocaml", project_root=str(tmp_path))
    with pytest.raises(ValueError) as exc:
        _default_spawn_fn(key)
    msg = str(exc.value)
    assert "ocaml" in msg
    for valid in (
        "rust", "python:pylsp-rope", "python:basedpyright",
        "python:ruff", "markdown",
    ):
        assert valid in msg


def test_rust_tag_dispatches_to_rust_analyzer(tmp_path):
    key = LspPoolKey(language="rust", project_root=str(tmp_path))
    fake_server = MagicMock(name="rust-analyzer-instance")
    with patch(
        "solidlsp.language_servers.rust_analyzer.RustAnalyzer"
    ) as mock_cls:
        mock_cls.return_value = fake_server
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner is fake_server
    assert mock_cls.called
    call_kwargs = mock_cls.call_args.kwargs or {}
    call_args = mock_cls.call_args.args
    config = call_kwargs.get("config") if "config" in call_kwargs else call_args[0]
    assert config is not None
    assert config.code_language.value == "rust"
    fake_server.start.assert_called_once()


def test_python_pylsp_rope_tag_dispatches_to_pylsp_server(tmp_path):
    key = LspPoolKey(
        language="python:pylsp-rope", project_root=str(tmp_path),
    )
    fake_server = MagicMock(name="pylsp-instance")
    with patch(
        "solidlsp.language_servers.pylsp_server.PylspServer"
    ) as mock_cls:
        mock_cls.return_value = fake_server
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner is fake_server
    assert mock_cls.called
    fake_server.start.assert_called_once()


def test_python_basedpyright_tag_dispatches_to_basedpyright_server(tmp_path):
    key = LspPoolKey(
        language="python:basedpyright", project_root=str(tmp_path),
    )
    fake_server = MagicMock(name="basedpyright-instance")
    with patch(
        "solidlsp.language_servers.basedpyright_server.BasedpyrightServer"
    ) as mock_cls:
        mock_cls.return_value = fake_server
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner is fake_server
    fake_server.start.assert_called_once()


def test_python_ruff_tag_dispatches_to_ruff_server(tmp_path):
    key = LspPoolKey(
        language="python:ruff", project_root=str(tmp_path),
    )
    fake_server = MagicMock(name="ruff-instance")
    with patch(
        "solidlsp.language_servers.ruff_server.RuffServer"
    ) as mock_cls:
        mock_cls.return_value = fake_server
        result = _default_spawn_fn(key)
    assert isinstance(result, _AsyncAdapter)
    assert result._inner is fake_server
    fake_server.start.assert_called_once()


def test_spawn_propagates_start_failure_without_caching(tmp_path):
    """Backlog #2: if .start() raises, spawn must surface the error.

    Otherwise downstream callers receive an _AsyncAdapter wrapping a never-
    initialised server and fail at the first LSP request with an opaque
    AttributeError instead of a clear startup failure.
    """
    key = LspPoolKey(language="rust", project_root=str(tmp_path))
    fake_server = MagicMock(name="rust-analyzer-instance")
    fake_server.start.side_effect = RuntimeError("rust-analyzer launch failed")
    with patch(
        "solidlsp.language_servers.rust_analyzer.RustAnalyzer"
    ) as mock_cls:
        mock_cls.return_value = fake_server
        with pytest.raises(RuntimeError, match="rust-analyzer launch failed"):
            _default_spawn_fn(key)


def test_async_adapter_wraps_sync_facade_methods_into_coroutines():
    """Verify the _AsyncAdapter pattern that fixes the sync/async wrapping gap.

    Stage 1H surfaced: MultiServerCoordinator.broadcast does
    `await getattr(server, facade_name)(**kwargs)`. Real Stage 1E adapters
    are sync, so this would raise TypeError. The _AsyncAdapter wraps the
    four facade methods so they return coroutines.
    """
    import asyncio

    class _SyncStub:
        def request_code_actions(self, **_kwargs):
            del _kwargs
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
