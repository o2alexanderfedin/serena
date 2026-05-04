"""PC1 Wave D: Additional coverage for WorkspaceHealthTool, TransactionRollbackTool
member_id None checkpoint, InstallLspServersTool NotImplementedError,
ExecuteCommandTool inner paths, facade_support additional branches,
and scalpel_runtime spawn dispatch edge cases.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(cls, project_root: str = "/tmp/pc1_wave_d"):
    tool = object.__new__(cls)
    tool.get_project_root = lambda: project_root
    return tool


# ============================================================================
# WorkspaceHealthTool — exception branch (coverage for lines 1347-1357)
# ============================================================================


class TestWorkspaceHealthTool:
    def test_apply_with_pool_exception_surfaces_failed_state(self, tmp_path):
        from serena.tools.scalpel_primitives import WorkspaceHealthTool
        from serena.tools.scalpel_runtime import ScalpelRuntime

        tool = _make_tool(WorkspaceHealthTool, str(tmp_path))

        mock_rt = MagicMock()
        # pool_for raises for every language → surfaces "failed" indexing state
        mock_rt.pool_for.side_effect = RuntimeError("pool unavailable")
        mock_rt.dynamic_capability_registry.return_value = MagicMock()
        mock_rt.catalog.return_value = MagicMock(records=[], hash=lambda: "")

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(project_root=str(tmp_path))

        result = json.loads(result_json)
        # The exception is caught per-language; both should be "failed"
        langs = result.get("languages", {})
        assert any(v.get("indexing_state") == "failed" for v in langs.values())

    def test_apply_with_explicit_project_root(self, tmp_path):
        from serena.tools.scalpel_primitives import WorkspaceHealthTool
        from serena.tools.scalpel_runtime import ScalpelRuntime

        tool = _make_tool(WorkspaceHealthTool, str(tmp_path))
        mock_rt = MagicMock()
        mock_rt.pool_for.side_effect = RuntimeError("no pool")
        mock_rt.dynamic_capability_registry.return_value = MagicMock()

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(project_root=str(tmp_path))

        result = json.loads(result_json)
        assert result["project_root"] == str(tmp_path.resolve())


# ============================================================================
# TransactionRollbackTool — None checkpoint branch (line 1228-1229)
# ============================================================================


class TestTransactionRollbackToolNoneCheckpoint:
    def test_none_checkpoint_in_member_ids_marks_step_noop(self, tmp_path):
        from serena.tools.scalpel_primitives import TransactionRollbackTool
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore
        from serena.refactoring.transactions import TransactionStore

        tool = _make_tool(TransactionRollbackTool, str(tmp_path))
        ckpt_store = CheckpointStore()
        txn_store = TransactionStore(checkpoint_store=ckpt_store)

        raw_id = txn_store.begin()
        # Register a checkpoint id that does NOT exist in the checkpoint store
        fake_cid = "nonexistent-checkpoint-id-xyz"
        txn_store.add_checkpoint(raw_id, fake_cid)

        mock_rt = MagicMock()
        mock_rt.transaction_store.return_value = txn_store
        mock_rt.checkpoint_store.return_value = ckpt_store

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(transaction_id=raw_id)
        result = json.loads(result_json)
        assert result["rolled_back"] is True  # transaction-level status
        step = result["per_step"][0]
        assert step["no_op"] is True  # individual step: no-op (ckpt is None)


# ============================================================================
# InstallLspServersTool — NotImplementedError branch (lines 1686-1699)
# ============================================================================


class TestInstallLspServersTool:
    def test_not_implemented_install_command_returns_skipped(self, tmp_path):
        from serena.tools.scalpel_primitives import InstallLspServersTool
        from serena.installer.installer import InstalledStatus

        tool = _make_tool(InstallLspServersTool, str(tmp_path))

        mock_installer = MagicMock()
        mock_installer.detect_installed.return_value = InstalledStatus(
            present=False, version=None, path=None
        )
        mock_installer.latest_available.return_value = "1.0"
        mock_installer._install_command.side_effect = NotImplementedError("not impl")

        mock_installer_cls = MagicMock(return_value=mock_installer)

        with patch(
            "serena.tools.scalpel_primitives._installer_registry",
            return_value={"test_lang": mock_installer_cls},
        ):
            result_json = tool.apply(languages=["test_lang"], dry_run=True)

        report = json.loads(result_json)
        assert "test_lang" in report
        assert report["test_lang"]["action"] == "skipped"
        assert "not impl" in report["test_lang"]["reason"]

    def test_detect_installed_raises_returns_skipped(self, tmp_path):
        from serena.tools.scalpel_primitives import InstallLspServersTool

        tool = _make_tool(InstallLspServersTool, str(tmp_path))

        mock_installer = MagicMock()
        mock_installer.detect_installed.side_effect = RuntimeError("cannot detect")
        mock_installer_cls = MagicMock(return_value=mock_installer)

        with patch(
            "serena.tools.scalpel_primitives._installer_registry",
            return_value={"bad_lang": mock_installer_cls},
        ):
            result_json = tool.apply(languages=["bad_lang"], dry_run=True)

        report = json.loads(result_json)
        assert report["bad_lang"]["action"] == "skipped"
        assert "cannot detect" in report["bad_lang"]["reason"]

    def test_install_action_with_allow_install_calls_install(self, tmp_path):
        from serena.tools.scalpel_primitives import InstallLspServersTool
        from serena.installer.installer import InstalledStatus, InstallResult

        tool = _make_tool(InstallLspServersTool, str(tmp_path))

        mock_installer = MagicMock()
        mock_installer.detect_installed.return_value = InstalledStatus(
            present=False, version=None, path=None
        )
        mock_installer.latest_available.return_value = "2.0"
        mock_installer._install_command.return_value = ["brew", "install", "marksman"]
        install_result = InstallResult(
            success=True,
            command_run=["brew", "install", "marksman"],
            stdout="installed",
            stderr="",
            return_code=0,
            dry_run=False,
        )
        mock_installer.install.return_value = install_result
        mock_installer_cls = MagicMock(return_value=mock_installer)

        with patch(
            "serena.tools.scalpel_primitives._installer_registry",
            return_value={"marksman": mock_installer_cls},
        ):
            result_json = tool.apply(
                languages=["marksman"],
                dry_run=False,
                allow_install=True,
            )

        report = json.loads(result_json)
        assert "marksman" in report
        assert report["marksman"]["dry_run"] is False
        mock_installer.install.assert_called_once_with(allow_install=True)

    def test_update_action_with_allow_update_calls_update(self, tmp_path):
        from serena.tools.scalpel_primitives import InstallLspServersTool
        from serena.installer.installer import InstalledStatus, InstallResult

        tool = _make_tool(InstallLspServersTool, str(tmp_path))

        mock_installer = MagicMock()
        mock_installer.detect_installed.return_value = InstalledStatus(
            present=True, version="1.0", path="/usr/bin/marksman"
        )
        mock_installer.latest_available.return_value = "2.0"
        mock_installer._install_command.return_value = ["brew", "upgrade", "marksman"]
        update_result = InstallResult(
            success=True,
            command_run=["brew", "upgrade", "marksman"],
            stdout="updated",
            stderr="",
            return_code=0,
        )
        mock_installer.update.return_value = update_result
        mock_installer_cls = MagicMock(return_value=mock_installer)

        with patch(
            "serena.tools.scalpel_primitives._installer_registry",
            return_value={"marksman": mock_installer_cls},
        ):
            result_json = tool.apply(
                languages=["marksman"],
                dry_run=False,
                allow_update=True,
            )

        report = json.loads(result_json)
        assert "marksman" in report
        mock_installer.update.assert_called_once_with(allow_update=True)


# ============================================================================
# ExecuteCommandTool — inner paths (lines 1489-1539)
# ============================================================================


class TestExecuteCommandToolInnerPaths:
    def test_command_in_allowlist_calls_coordinator(self, tmp_path):
        from serena.tools.scalpel_primitives import ExecuteCommandTool
        from serena.tools.scalpel_runtime import ScalpelRuntime

        tool = _make_tool(ExecuteCommandTool, str(tmp_path))

        mock_coord = MagicMock()
        mock_coord.servers = ["pylsp-rope"]
        mock_coord.execute_command_allowlist.return_value = frozenset({"pylsp.executeCommand"})
        mock_coord.broadcast.return_value = MagicMock(timeouts=[])

        mock_rt = MagicMock()
        mock_rt.coordinator_for.return_value = mock_coord

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(command="pylsp.executeCommand", language="python")

        result = json.loads(result_json)
        assert result["applied"] is True

    def test_command_not_in_allowlist_returns_failure(self, tmp_path):
        from serena.tools.scalpel_primitives import ExecuteCommandTool
        from serena.tools.scalpel_runtime import ScalpelRuntime

        tool = _make_tool(ExecuteCommandTool, str(tmp_path))

        mock_coord = MagicMock()
        mock_coord.servers = ["pylsp-rope"]
        mock_coord.execute_command_allowlist.return_value = frozenset()  # empty live list

        mock_rt = MagicMock()
        mock_rt.coordinator_for.return_value = mock_coord

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(command="forbidden.command", language="python")

        result = json.loads(result_json)
        assert result["applied"] is False
        assert result.get("failure") is not None

    def test_default_language_used_when_not_provided(self, tmp_path):
        from serena.tools.scalpel_primitives import ExecuteCommandTool
        from serena.tools.scalpel_runtime import ScalpelRuntime

        tool = _make_tool(ExecuteCommandTool, str(tmp_path))

        mock_coord = MagicMock()
        mock_coord.servers = ["pylsp-rope"]
        # The static fallback for python includes pylsp.executeCommand
        mock_coord.execute_command_allowlist.return_value = frozenset()

        mock_rt = MagicMock()
        mock_rt.coordinator_for.return_value = mock_coord

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            # No language= → uses DEFAULT_LANGUAGE="python"
            result_json = tool.apply(command="pylsp.executeCommand")

        result = json.loads(result_json)
        # pylsp.executeCommand is in the python fallback, so should succeed
        # but since live allowlist is empty, fallback is used → applied
        assert result.get("applied") is True


# ============================================================================
# facade_support: apply_action_and_checkpoint (lines 408-420)
# ============================================================================


class TestApplyActionAndCheckpoint:
    def test_none_edit_resolution_produces_empty_checkpoint(self, tmp_path):
        from serena.tools.facade_support import apply_action_and_checkpoint
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore

        mock_coord = MagicMock()
        mock_coord.resolve_edit.return_value = None

        # _resolve_winner_edit returns None for an unresolvable action
        cs = CheckpointStore()
        mock_rt = MagicMock()
        mock_rt.checkpoint_store.return_value = cs

        mock_action = MagicMock()

        with patch("serena.tools.facade_support._resolve_winner_edit", return_value=None):
            with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
                cid, applied_edit = apply_action_and_checkpoint(mock_coord, mock_action)

        assert cid != ""  # checkpoint was recorded even for empty edit
        assert applied_edit == {"changes": {}}

    def test_real_edit_applies_and_checkpoints(self, tmp_path):
        from serena.tools.facade_support import apply_action_and_checkpoint
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore

        f = tmp_path / "target.py"
        f.write_text("old content", encoding="utf-8")
        uri = f.as_uri()
        edit = {
            "changes": {
                uri: [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 11},
                        },
                        "newText": "new content",
                    }
                ]
            }
        }

        cs = CheckpointStore()
        mock_rt = MagicMock()
        mock_rt.checkpoint_store.return_value = cs
        mock_coord = MagicMock()
        mock_action = MagicMock()

        with patch("serena.tools.facade_support._resolve_winner_edit", return_value=edit):
            with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
                cid, applied_edit = apply_action_and_checkpoint(mock_coord, mock_action)

        assert cid != ""
        assert f.read_text() == "new content"


# ============================================================================
# facade_support: inverse_apply_checkpoint (lines 647-650)
# ============================================================================


class TestInverseApplyCheckpoint:
    def test_unknown_checkpoint_id_returns_false_empty(self):
        from serena.tools.facade_support import inverse_apply_checkpoint
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore

        cs = CheckpointStore()
        mock_rt = MagicMock()
        mock_rt.checkpoint_store.return_value = cs

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            ok, warnings = inverse_apply_checkpoint("nonexistent-cid-xyz")

        assert ok is False
        assert warnings == []

    def test_known_checkpoint_restores_text(self, tmp_path):
        from serena.tools.facade_support import inverse_apply_checkpoint
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore

        f = tmp_path / "restore.py"
        f.write_text("post-edit content", encoding="utf-8")
        uri = f.as_uri()

        cs = CheckpointStore()
        cid = cs.record(
            applied={"changes": {uri: []}},
            snapshot={uri: "pre-edit content"},
        )
        mock_rt = MagicMock()
        mock_rt.checkpoint_store.return_value = cs

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            ok, warnings = inverse_apply_checkpoint(cid)

        assert ok is True
        assert f.read_text() == "pre-edit content"


# ============================================================================
# facade_support: attach_apply_source / get_apply_source (lines 840-873)
# ============================================================================


class TestAttachAndGetApplySource:
    def test_get_apply_source_returns_source_string(self):
        from serena.tools.facade_support import get_apply_source
        from serena.tools.scalpel_facades import SplitFileTool

        src = get_apply_source(SplitFileTool)
        assert "def apply" in src

    def test_get_apply_source_returns_empty_for_no_apply(self):
        from serena.tools.facade_support import get_apply_source

        class NoApply:
            pass

        src = get_apply_source(NoApply)
        assert src == ""

    def test_attach_apply_source_idempotent(self):
        from serena.tools.facade_support import attach_apply_source
        from serena.tools.scalpel_facades import SplitFileTool

        # Should not raise; calling twice is idempotent
        attach_apply_source(SplitFileTool)
        attach_apply_source(SplitFileTool)
        assert hasattr(SplitFileTool.apply, "__wrapped_source__")


# ============================================================================
# scalpel_runtime: _default_spawn_fn known language (line 205)
# ============================================================================


class TestDefaultSpawnFnKnownLanguage:
    def test_known_language_calls_spawn_function(self, tmp_path):
        from serena.tools.scalpel_runtime import _default_spawn_fn, LspPoolKey
        import serena.tools.scalpel_runtime as _mod

        # Mock the underlying spawn function so we don't start a real server
        mock_server = MagicMock()
        mock_spawn_fn = MagicMock(return_value=mock_server)

        original_table = dict(_mod._SPAWN_DISPATCH_TABLE)
        _mod._SPAWN_DISPATCH_TABLE["rust"] = mock_spawn_fn
        try:
            key = LspPoolKey(language="rust", project_root=str(tmp_path))
            result = _default_spawn_fn(key)
        finally:
            _mod._SPAWN_DISPATCH_TABLE.clear()
            _mod._SPAWN_DISPATCH_TABLE.update(original_table)

        assert result is mock_server
        mock_spawn_fn.assert_called_once_with(key)


# ============================================================================
# facade_support: _uri_to_path edge cases
# ============================================================================


class TestUriToPath:
    def test_file_uri_returns_path(self, tmp_path):
        from serena.tools.facade_support import _uri_to_path

        f = tmp_path / "test.py"
        path = _uri_to_path(f.as_uri())
        assert path == f

    def test_non_file_uri_returns_none(self):
        from serena.tools.facade_support import _uri_to_path

        result = _uri_to_path("https://example.com/foo.py")
        assert result is None


# ============================================================================
# facade_support: _apply_text_edits_to_file_uri edge cases
# ============================================================================


class TestApplyTextEditsToFileUri:
    def test_non_file_uri_returns_zero(self):
        from serena.tools.facade_support import _apply_text_edits_to_file_uri

        result = _apply_text_edits_to_file_uri("https://example.com/f.py", [{"range": {}, "newText": "x"}])
        assert result == 0

    def test_empty_edits_returns_zero(self, tmp_path):
        from serena.tools.facade_support import _apply_text_edits_to_file_uri

        f = tmp_path / "f.py"
        f.write_text("hello", encoding="utf-8")
        result = _apply_text_edits_to_file_uri(f.as_uri(), [])
        assert result == 0

    def test_missing_file_returns_zero(self, tmp_path):
        from serena.tools.facade_support import _apply_text_edits_to_file_uri

        uri = (tmp_path / "missing.py").as_uri()
        result = _apply_text_edits_to_file_uri(
            uri,
            [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "newText": "x"}],
        )
        assert result == 0

    def test_idempotent_edit_returns_zero(self, tmp_path):
        from serena.tools.facade_support import _apply_text_edits_to_file_uri

        f = tmp_path / "f.py"
        f.write_text("hello\n", encoding="utf-8")
        # Apply edit that changes "hello" to "hello" (no actual change)
        edits = [
            {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 5},
                },
                "newText": "hello",
            }
        ]
        result = _apply_text_edits_to_file_uri(f.as_uri(), edits)
        assert result == 0  # idempotent guard: same text → skip write


# ============================================================================
# scalpel_facades: _infer_language edge cases
# ============================================================================


class TestInferLanguage:
    def _import(self):
        from serena.tools.scalpel_facades import _infer_language
        return _infer_language

    def test_rs_extension_returns_rust(self):
        fn = self._import()
        assert fn("lib.rs", None) == "rust"

    def test_py_extension_returns_python(self):
        fn = self._import()
        assert fn("main.py", None) == "python"

    def test_explicit_language_overrides_extension(self):
        fn = self._import()
        assert fn("lib.rs", "python") == "python"

    def test_unknown_extension_returns_unknown(self):
        fn = self._import()
        result = fn("lib.unknown", None)
        assert result not in ("rust", "python")

    def test_unknown_extension_does_not_return_rust_or_python(self):
        fn = self._import()
        result = fn("lib.cpp", None)
        assert result not in ("rust", "python")


# ============================================================================
# scalpel_primitives: _strip_txn_prefix
# ============================================================================


class TestStripTxnPrefix:
    def _import(self):
        from serena.tools.scalpel_facades import _strip_txn_prefix
        return _strip_txn_prefix

    def test_strips_txn_underscore_prefix(self):
        fn = self._import()
        assert fn("txn_abc123") == "abc123"

    def test_no_prefix_unchanged(self):
        fn = self._import()
        assert fn("abc123") == "abc123"

    def test_txn_colon_not_stripped(self):
        fn = self._import()
        assert fn("txn:abc123") == "txn:abc123"
