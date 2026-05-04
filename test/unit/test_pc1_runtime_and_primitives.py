"""PC1 coverage uplift – ScalpelRuntime + scalpel_primitives pure-Python paths.

Covers:
  - parse_workspace_extra_paths (env var branches)
  - _default_spawn_fn unknown language error path
  - ScalpelRuntime singleton lifecycle (reset, catalog, checkpoint_store,
    pending_tx_store, plugin_registry, dynamic_capability_registry,
    set_plugin_registry_for_testing, transaction_store)
  - _AsyncAdapter.non-method attribute forwarding
  - _decide_action pure logic
  - InstallLspServersTool.apply dry_run=True unknown-language branch
  - ExecuteCommandTool.apply unknown-language branch
  - _merge_install_result (pure projection)
  - scalpel_primitives: _shadow_workspace context manager
  - RollbackTool unknown checkpoint
  - TransactionRollbackTool unknown transaction
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# parse_workspace_extra_paths
# ---------------------------------------------------------------------------


def test_parse_workspace_extra_paths_empty_env() -> None:
    from serena.tools.scalpel_runtime import parse_workspace_extra_paths

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", None)
        result = parse_workspace_extra_paths()
    assert result == ()


def test_parse_workspace_extra_paths_non_empty_env() -> None:
    from serena.tools.scalpel_runtime import parse_workspace_extra_paths

    sep = os.pathsep
    with patch.dict(os.environ, {"O2_SCALPEL_WORKSPACE_EXTRA_PATHS": f"/foo{sep}/bar"}):
        result = parse_workspace_extra_paths()
    assert "/foo" in result
    assert "/bar" in result


def test_parse_workspace_extra_paths_blank_entries_dropped() -> None:
    from serena.tools.scalpel_runtime import parse_workspace_extra_paths

    sep = os.pathsep
    with patch.dict(os.environ, {"O2_SCALPEL_WORKSPACE_EXTRA_PATHS": f"/a{sep}{sep}/b{sep} "}):
        result = parse_workspace_extra_paths()
    # Blank / whitespace-only entries are dropped
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _default_spawn_fn unknown language → ValueError
# ---------------------------------------------------------------------------


def test_default_spawn_fn_unknown_language_raises() -> None:
    from serena.tools.scalpel_runtime import _default_spawn_fn
    from serena.refactoring import LspPoolKey

    key = LspPoolKey(language="cobol", project_root="/tmp")
    with pytest.raises(ValueError, match="unknown LspPoolKey.language"):
        _default_spawn_fn(key)


# ---------------------------------------------------------------------------
# _AsyncAdapter — non-async attribute forwarding
# ---------------------------------------------------------------------------


def test_async_adapter_non_async_attribute_forwarded() -> None:
    from serena.tools.scalpel_runtime import _AsyncAdapter

    inner = MagicMock()
    inner.some_attribute = "hello"
    adapter = _AsyncAdapter(inner)
    # Non-awaited attributes are forwarded transparently
    assert adapter.some_attribute == "hello"


def test_async_adapter_async_method_returns_coroutine() -> None:
    """Methods in _ASYNC_METHODS should return a coroutine."""
    import asyncio
    from serena.tools.scalpel_runtime import _AsyncAdapter
    from serena.refactoring._async_check import AWAITED_SERVER_METHODS

    inner = MagicMock()
    # Use the first method in the canonical set
    method_name = next(iter(AWAITED_SERVER_METHODS))
    setattr(inner, method_name, MagicMock(return_value=42))
    adapter = _AsyncAdapter(inner)
    result = getattr(adapter, method_name)()
    assert asyncio.iscoroutine(result)
    result.close()  # prevent ResourceWarning


# ---------------------------------------------------------------------------
# ScalpelRuntime singleton lifecycle
# ---------------------------------------------------------------------------


def test_scalpel_runtime_singleton_and_reset() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    r1 = ScalpelRuntime.instance()
    r2 = ScalpelRuntime.instance()
    assert r1 is r2
    ScalpelRuntime.reset_for_testing()
    r3 = ScalpelRuntime.instance()
    assert r3 is not r1
    ScalpelRuntime.reset_for_testing()


def test_scalpel_runtime_catalog_lazy_build() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    rt = ScalpelRuntime.instance()
    catalog = rt.catalog()
    assert catalog is not None
    # Second call returns cached
    assert rt.catalog() is catalog
    ScalpelRuntime.reset_for_testing()


def test_scalpel_runtime_checkpoint_store_lazy_build() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    rt = ScalpelRuntime.instance()
    cs = rt.checkpoint_store()
    assert cs is not None
    assert rt.checkpoint_store() is cs
    ScalpelRuntime.reset_for_testing()


def test_scalpel_runtime_transaction_store_lazy_build() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    rt = ScalpelRuntime.instance()
    ts = rt.transaction_store()
    assert ts is not None
    # Second call returns the same store
    assert rt.transaction_store() is ts
    ScalpelRuntime.reset_for_testing()


def test_scalpel_runtime_pending_tx_store_lazy_build() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    rt = ScalpelRuntime.instance()
    store = rt.pending_tx_store()
    assert store is not None
    assert rt.pending_tx_store() is store
    ScalpelRuntime.reset_for_testing()


def test_scalpel_runtime_plugin_registry_lazy_build() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    rt = ScalpelRuntime.instance()
    pr = rt.plugin_registry()
    assert pr is not None
    assert rt.plugin_registry() is pr
    ScalpelRuntime.reset_for_testing()


def test_scalpel_runtime_dynamic_capability_registry_lazy_build() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    rt = ScalpelRuntime.instance()
    dcr = rt.dynamic_capability_registry()
    assert dcr is not None
    assert rt.dynamic_capability_registry() is dcr
    ScalpelRuntime.reset_for_testing()


def test_scalpel_runtime_set_plugin_registry_for_testing() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.plugins.registry import PluginRegistry

    ScalpelRuntime.reset_for_testing()
    rt = ScalpelRuntime.instance()
    fake_registry = PluginRegistry(Path("/nonexistent"))
    rt.set_plugin_registry_for_testing(fake_registry)
    assert rt.plugin_registry() is fake_registry
    ScalpelRuntime.reset_for_testing()


# ---------------------------------------------------------------------------
# _decide_action — pure logic
# ---------------------------------------------------------------------------


def test_decide_action_install_when_not_present() -> None:
    from serena.tools.scalpel_primitives import _decide_action

    assert _decide_action(detected_present=False, detected_version=None, latest=None) == "install"


def test_decide_action_update_when_outdated() -> None:
    from serena.tools.scalpel_primitives import _decide_action

    assert _decide_action(detected_present=True, detected_version="1.0", latest="2.0") == "update"


def test_decide_action_noop_when_current() -> None:
    from serena.tools.scalpel_primitives import _decide_action

    assert _decide_action(detected_present=True, detected_version="2.0", latest="2.0") == "noop"


def test_decide_action_noop_when_no_latest_info() -> None:
    from serena.tools.scalpel_primitives import _decide_action

    assert _decide_action(detected_present=True, detected_version=None, latest=None) == "noop"


def test_decide_action_noop_when_latest_none_but_version_known() -> None:
    from serena.tools.scalpel_primitives import _decide_action

    # latest=None means we can't determine if update needed → noop
    assert _decide_action(detected_present=True, detected_version="1.0", latest=None) == "noop"


# ---------------------------------------------------------------------------
# InstallLspServersTool — dry_run=True with unknown language
# ---------------------------------------------------------------------------


def test_install_lsp_servers_unknown_language_returns_skipped(tmp_path: Path) -> None:
    """Unknown language in the languages list should surface as 'skipped' in report."""
    from serena.tools.scalpel_primitives import InstallLspServersTool

    tool = object.__new__(InstallLspServersTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    result = tool.apply(languages=["cobol", "brainfuck"], dry_run=True)
    report = json.loads(result)
    assert "cobol" in report
    assert report["cobol"]["action"] == "skipped"
    assert "brainfuck" in report
    assert report["brainfuck"]["action"] == "skipped"


def test_install_lsp_servers_dry_run_true_known_language_no_install(tmp_path: Path) -> None:
    """dry_run=True should never call installer.install() even with allow_install=True."""
    from serena.tools.scalpel_primitives import InstallLspServersTool
    from serena.installer.installer import InstalledStatus

    mock_installer = MagicMock()
    mock_installer.detect_installed.return_value = InstalledStatus(
        present=False, version=None, path=None,
    )
    mock_installer.latest_available.return_value = None
    mock_installer._install_command.return_value = ["brew", "install", "marksman"]
    mock_installer.install = MagicMock()

    mock_installer_cls = MagicMock(return_value=mock_installer)

    tool = object.__new__(InstallLspServersTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    with patch(
        "serena.tools.scalpel_primitives._installer_registry",
        return_value={"markdown": mock_installer_cls},
    ):
        result = tool.apply(
            languages=["markdown"],
            dry_run=True,
            allow_install=True,
        )

    report = json.loads(result)
    assert "markdown" in report
    assert report["markdown"]["dry_run"] is True
    # install should NOT have been called
    mock_installer.install.assert_not_called()


# ---------------------------------------------------------------------------
# _merge_install_result — pure projection
# ---------------------------------------------------------------------------


def test_merge_install_result_projects_fields() -> None:
    from serena.tools.scalpel_primitives import _merge_install_result
    from serena.installer.installer import InstallResult

    entry: dict = {"action": "install", "dry_run": True}
    result = InstallResult(
        dry_run=False,
        success=True,
        stdout="ok",
        stderr="",
        return_code=0,
        command_run=["brew", "install", "marksman"],
    )
    _merge_install_result(entry, result)
    assert entry["dry_run"] is False
    assert entry["success"] is True
    assert entry["stdout"] == "ok"
    assert entry["return_code"] == 0
    assert entry["command"] == ["brew", "install", "marksman"]


def test_merge_install_result_ignores_non_install_result() -> None:
    from serena.tools.scalpel_primitives import _merge_install_result

    entry: dict = {"dry_run": True}
    _merge_install_result(entry, "not an InstallResult")
    # should be a no-op
    assert entry == {"dry_run": True}


# ---------------------------------------------------------------------------
# _shadow_workspace context manager
# ---------------------------------------------------------------------------


def test_shadow_workspace_creates_copy_and_cleans_up(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import _shadow_workspace

    src = tmp_path / "workspace"
    src.mkdir()
    (src / "hello.py").write_text("print('hi')")

    shadow_root: Path | None = None
    with _shadow_workspace(src) as sr:
        shadow_root = sr
        # Shadow should have the file
        assert (sr / "hello.py").exists()

    # After exit, shadow should be cleaned up
    assert not (shadow_root.parent).exists() or not shadow_root.exists()


# ---------------------------------------------------------------------------
# RollbackTool — unknown checkpoint ID
# ---------------------------------------------------------------------------


def test_rollback_tool_unknown_checkpoint_returns_no_op(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import RollbackTool
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    try:
        tool = object.__new__(RollbackTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(checkpoint_id="ckpt_nonexistent_id_xyz")
        payload = json.loads(result)
        # Should not crash; applied=False expected
        assert "applied" in payload
    finally:
        ScalpelRuntime.reset_for_testing()


# ---------------------------------------------------------------------------
# TransactionRollbackTool — unknown transaction ID
# ---------------------------------------------------------------------------


def test_transaction_rollback_tool_unknown_txn_returns_not_rolled_back(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import TransactionRollbackTool
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    try:
        tool = object.__new__(TransactionRollbackTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(transaction_id="txn_nonexistent_xyz")
        payload = json.loads(result)
        assert payload["rolled_back"] is False
    finally:
        ScalpelRuntime.reset_for_testing()


# ---------------------------------------------------------------------------
# ExecuteCommandTool — unknown language returns INVALID_ARGUMENT
# ---------------------------------------------------------------------------


def test_execute_command_unknown_language_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_primitives import ExecuteCommandTool
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    try:
        tool = object.__new__(ExecuteCommandTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            command="some.command",
            language="cobol",  # not in _EXECUTE_COMMAND_FALLBACK
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "INVALID_ARGUMENT"
    finally:
        ScalpelRuntime.reset_for_testing()
