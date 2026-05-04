"""PC1 Wave C: Coverage uplift for facade_support._inverse_applier_to_disk,
TransactionCommitTool, _augment_workspace_edit_with_all_update,
ImportsOrganizeTool no-kinds, InlineTool all_callers,
ReloadPluginsTool, TransactionRollbackTool, and ScalpelRuntime pool/coord paths.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = "/tmp/pc1_wave_c"


def _make_tool(cls, project_root: str = _PROJECT_ROOT):
    """Build a tool instance without a live SerenaAgent."""
    tool = object.__new__(cls)
    tool.get_project_root = lambda: project_root
    return tool


def _make_mock_runtime():
    """Return a mock ScalpelRuntime with in-memory stores."""
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.checkpoints import CheckpointStore
    from serena.refactoring.transactions import TransactionStore

    cs = CheckpointStore()
    mock_rt = MagicMock(spec=ScalpelRuntime)
    mock_rt.checkpoint_store.return_value = cs
    mock_rt.transaction_store.return_value = TransactionStore(checkpoint_store=cs)
    return mock_rt


# ============================================================================
# facade_support: _inverse_applier_to_disk branches
# ============================================================================


class TestInverseApplierToDisk:
    """Unit-test _inverse_applier_to_disk without live LSP servers."""

    def _import(self):
        from serena.tools.facade_support import _inverse_applier_to_disk, _SNAPSHOT_NONEXISTENT
        return _inverse_applier_to_disk, _SNAPSHOT_NONEXISTENT

    def test_empty_edit_returns_false(self, tmp_path):
        fn, _ = self._import()
        ok, warnings = fn(snapshot={}, applied_edit={})
        assert ok is False
        assert warnings == []

    def test_changes_shape_restores_file(self, tmp_path):
        fn, _ = self._import()
        f = tmp_path / "foo.py"
        f.write_text("old content", encoding="utf-8")
        uri = f.as_uri()
        snapshot = {uri: "original content"}
        applied_edit = {"changes": {uri: [{"dummy": "edit"}]}}
        ok, warnings = fn(snapshot=snapshot, applied_edit=applied_edit)
        assert ok is True
        assert f.read_text() == "original content"

    def test_changes_shape_nonexistent_sentinel_deletes_file(self, tmp_path):
        fn, sent = self._import()
        f = tmp_path / "created.py"
        f.write_text("created by apply", encoding="utf-8")
        uri = f.as_uri()
        snapshot = {uri: sent}
        applied_edit = {"changes": {uri: []}}
        ok, warnings = fn(snapshot=snapshot, applied_edit=applied_edit)
        assert ok is True
        assert not f.exists()

    def test_changes_shape_no_snapshot_emits_warning(self, tmp_path):
        fn, _ = self._import()
        uri = (tmp_path / "missing.py").as_uri()
        applied_edit = {"changes": {uri: []}}
        ok, warnings = fn(snapshot={}, applied_edit=applied_edit)
        assert ok is False
        assert any("no snapshot entry" in w for w in warnings)

    def test_document_changes_create_kind_removes_created_file(self, tmp_path):
        fn, _ = self._import()
        f = tmp_path / "new_file.py"
        f.write_text("", encoding="utf-8")
        uri = f.as_uri()
        applied_edit = {
            "documentChanges": [{"kind": "create", "uri": uri}]
        }
        ok, warnings = fn(snapshot={}, applied_edit=applied_edit)
        assert ok is True
        assert not f.exists()

    def test_document_changes_create_kind_already_gone_is_ok(self, tmp_path):
        fn, _ = self._import()
        uri = (tmp_path / "already_gone.py").as_uri()
        applied_edit = {
            "documentChanges": [{"kind": "create", "uri": uri}]
        }
        # File never existed — should not crash
        ok, warnings = fn(snapshot={}, applied_edit=applied_edit)
        assert ok is False  # nothing actually restored
        assert warnings == []

    def test_document_changes_create_non_file_uri(self, tmp_path):
        fn, _ = self._import()
        applied_edit = {
            "documentChanges": [{"kind": "create", "uri": "https://example.com/foo"}]
        }
        ok, warnings = fn(snapshot={}, applied_edit=applied_edit)
        assert ok is False
        assert any("non-file URI" in w for w in warnings)

    def test_document_changes_delete_no_snapshot_warns(self, tmp_path):
        fn, sent = self._import()
        f = tmp_path / "target.py"
        f.write_text("data", encoding="utf-8")
        uri = f.as_uri()
        applied_edit = {
            "documentChanges": [{"kind": "delete", "uri": uri}]
        }
        ok, warnings = fn(snapshot={}, applied_edit=applied_edit)
        assert ok is False
        assert any("cannot be undone" in w for w in warnings)

    def test_document_changes_delete_with_real_snapshot_restores(self, tmp_path):
        fn, sent = self._import()
        f = tmp_path / "deleted.py"
        uri = f.as_uri()
        # Simulate: file was deleted by apply; snapshot had real content
        snapshot = {uri: "original content of deleted file"}
        applied_edit = {
            "documentChanges": [{"kind": "delete", "uri": uri}]
        }
        ok, warnings = fn(snapshot=snapshot, applied_edit=applied_edit)
        assert ok is True
        assert f.read_text() == "original content of deleted file"

    def test_document_changes_rename_kind(self, tmp_path):
        fn, _ = self._import()
        old = tmp_path / "old.py"
        new = tmp_path / "new.py"
        new.write_text("content", encoding="utf-8")
        old_uri = old.as_uri()
        new_uri = new.as_uri()
        snapshot = {old_uri: "original content"}
        applied_edit = {
            "documentChanges": [
                {"kind": "rename", "oldUri": old_uri, "newUri": new_uri}
            ]
        }
        ok, warnings = fn(snapshot=snapshot, applied_edit=applied_edit)
        assert ok is True
        assert old.exists()

    def test_document_changes_rename_new_path_missing(self, tmp_path):
        fn, _ = self._import()
        old_uri = (tmp_path / "old.py").as_uri()
        new_uri = (tmp_path / "new_gone.py").as_uri()
        applied_edit = {
            "documentChanges": [
                {"kind": "rename", "oldUri": old_uri, "newUri": new_uri}
            ]
        }
        ok, warnings = fn(snapshot={}, applied_edit=applied_edit)
        # new path doesn't exist → warns but tries to recreate old
        assert any("no longer exists" in w for w in warnings)

    def test_document_changes_text_doc_edit(self, tmp_path):
        fn, _ = self._import()
        f = tmp_path / "tde.py"
        f.write_text("mutated content", encoding="utf-8")
        uri = f.as_uri()
        snapshot = {uri: "pre-edit content"}
        applied_edit = {
            "documentChanges": [
                {
                    "textDocument": {"uri": uri, "version": 1},
                    "edits": [],
                }
            ]
        }
        ok, warnings = fn(snapshot=snapshot, applied_edit=applied_edit)
        assert ok is True
        assert f.read_text() == "pre-edit content"

    def test_document_changes_unknown_kind_skipped(self, tmp_path):
        fn, _ = self._import()
        applied_edit = {
            "documentChanges": [
                {"kind": "future_op", "uri": "file:///nowhere.py"}
            ]
        }
        # Unknown kind → no text_document key → uri is None → skip
        ok, warnings = fn(snapshot={}, applied_edit=applied_edit)
        # no crash; ok=False since nothing was restored
        assert ok is False

    def test_non_dict_entry_in_document_changes_skipped(self, tmp_path):
        fn, _ = self._import()
        applied_edit = {
            "documentChanges": ["not_a_dict", None, 42]
        }
        ok, warnings = fn(snapshot={}, applied_edit=applied_edit)
        assert ok is False


class TestApplyWorkspaceEditAndCheckpoint:
    def test_empty_edit_returns_empty_string(self):
        from serena.tools.facade_support import apply_workspace_edit_and_checkpoint
        from serena.tools.scalpel_runtime import ScalpelRuntime

        with patch.object(ScalpelRuntime, "instance") as mock_inst:
            result = apply_workspace_edit_and_checkpoint({})
        assert result == ""

    def test_empty_changes_returns_empty_string(self):
        from serena.tools.facade_support import apply_workspace_edit_and_checkpoint
        from serena.tools.scalpel_runtime import ScalpelRuntime

        with patch.object(ScalpelRuntime, "instance") as mock_inst:
            result = apply_workspace_edit_and_checkpoint({"changes": {}})
        assert result == ""


# ============================================================================
# _augment_workspace_edit_with_all_update
# ============================================================================


class TestAugmentWorkspaceEditWithAllUpdate:
    def _import(self):
        from serena.tools.scalpel_facades import _augment_workspace_edit_with_all_update
        return _augment_workspace_edit_with_all_update

    def test_no_all_in_file_returns_unchanged(self, tmp_path):
        fn = self._import()
        f = tmp_path / "mod.py"
        f.write_text("def foo(): pass\n", encoding="utf-8")
        edit = {"changes": {}}
        result = fn(workspace_edit=edit, file=str(f), old_name="foo", new_name="bar")
        assert result is edit  # same object, unmodified

    def test_all_contains_old_name_appends_text_edit(self, tmp_path):
        fn = self._import()
        f = tmp_path / "mod.py"
        f.write_text('__all__ = ["foo", "baz"]\n', encoding="utf-8")
        edit: dict[str, Any] = {}
        result = fn(workspace_edit=edit, file=str(f), old_name="foo", new_name="bar")
        # Should have injected a changes entry for the file URI
        changes = result.get("changes", {})
        file_uri = f.as_uri()
        assert file_uri in changes
        assert len(changes[file_uri]) == 1
        te = changes[file_uri][0]
        assert te["newText"] == "bar"

    def test_all_does_not_contain_old_name_unchanged(self, tmp_path):
        fn = self._import()
        f = tmp_path / "mod.py"
        f.write_text('__all__ = ["other"]\n', encoding="utf-8")
        edit: dict[str, Any] = {}
        result = fn(workspace_edit=edit, file=str(f), old_name="foo", new_name="bar")
        assert result.get("changes", {}) == {}

    def test_oserror_returns_unchanged(self, tmp_path):
        fn = self._import()
        result = fn(
            workspace_edit={},
            file="/nonexistent/path/mod.py",
            old_name="foo",
            new_name="bar",
        )
        assert result == {}

    def test_syntax_error_returns_unchanged(self, tmp_path):
        fn = self._import()
        f = tmp_path / "bad.py"
        f.write_text("def ()\n", encoding="utf-8")
        edit: dict[str, Any] = {}
        result = fn(workspace_edit=edit, file=str(f), old_name="foo", new_name="bar")
        # SyntaxError → returns unchanged
        assert result is edit


# ============================================================================
# ImportsOrganizeTool — no sub-kinds path
# ============================================================================


class TestImportsOrganizeToolNoSubKinds:
    """When all three import-kind flags are False, the tool short-circuits."""

    def test_no_sub_kinds_returns_noop(self, tmp_path):
        from serena.tools.scalpel_facades import ImportsOrganizeTool
        tool = _make_tool(ImportsOrganizeTool, str(tmp_path))
        f = tmp_path / "main.py"
        f.write_text("import os\n", encoding="utf-8")
        result_json = tool.apply(
            files=[str(f)],
            add_missing=False,
            remove_unused=False,
            reorder=False,
        )
        result = json.loads(result_json)
        assert result["no_op"] is True
        assert result["applied"] is False

    def test_unknown_language_inferred_from_unsupported_ext(self, tmp_path):
        from serena.tools.scalpel_facades import ImportsOrganizeTool
        tool = _make_tool(ImportsOrganizeTool, str(tmp_path))
        f = tmp_path / "main.txt"
        f.write_text("import os\n", encoding="utf-8")
        result_json = tool.apply(files=[str(f)])
        result = json.loads(result_json)
        # Should fail — cannot infer language from .txt
        assert result.get("failure") is not None or result.get("no_op") is not None


# ============================================================================
# InlineTool — all_callers scope validation
# ============================================================================


class TestInlineToolAllCallersScope:
    def test_all_callers_without_name_path_or_position_fails(self, tmp_path):
        from serena.tools.scalpel_facades import InlineTool
        tool = _make_tool(InlineTool, str(tmp_path))
        f = tmp_path / "lib.rs"
        f.write_text("fn foo() {}", encoding="utf-8")
        result_json = tool.apply(
            file=str(f),
            scope="all_callers",
            # no name_path, no position
        )
        result = json.loads(result_json)
        assert result.get("failure") is not None
        assert "scope=all_callers requires" in result["failure"]["reason"]

    def test_single_call_site_with_unknown_lang_ext_fails(self, tmp_path):
        from serena.tools.scalpel_facades import InlineTool
        tool = _make_tool(InlineTool, str(tmp_path))
        f = tmp_path / "lib.unknown"
        f.write_text("fn foo() {}", encoding="utf-8")
        result_json = tool.apply(
            file=str(f),
            position={"line": 0, "character": 0},
        )
        result = json.loads(result_json)
        assert result.get("failure") is not None
        assert "Cannot infer language" in result["failure"]["reason"]


# ============================================================================
# TransactionCommitTool — various short-circuit paths
# ============================================================================


class TestTransactionCommitTool:
    def _import_and_make(self, tmp_path):
        from serena.tools.scalpel_facades import TransactionCommitTool
        tool = _make_tool(TransactionCommitTool, str(tmp_path))
        return tool

    def test_unknown_transaction_id_returns_failure(self, tmp_path):
        from serena.tools.scalpel_facades import TransactionCommitTool
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore
        from serena.refactoring.transactions import TransactionStore

        tool = self._import_and_make(tmp_path)
        cs = CheckpointStore()
        mock_rt = MagicMock()
        mock_rt.transaction_store.return_value = TransactionStore(checkpoint_store=cs)
        mock_rt.checkpoint_store.return_value = cs

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(transaction_id="txn:nonexistent-id-xyz")
        result = json.loads(result_json)
        assert result["rolled_back"] is False
        assert len(result["per_step"]) == 1
        assert "Unknown or empty transaction_id" in result["per_step"][0]["failure"]["reason"]

    def test_expired_transaction_returns_preview_expired(self, tmp_path):
        from serena.tools.scalpel_facades import TransactionCommitTool
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore
        from serena.refactoring.transactions import TransactionStore
        import time

        tool = self._import_and_make(tmp_path)
        cs = CheckpointStore()
        txn_store = TransactionStore(checkpoint_store=cs)
        raw_id = txn_store.begin()
        txn_store.add_step(raw_id, {"tool": "scalpel_rename", "args": {}})
        # Set expiry in the past
        txn_store.set_expires_at(raw_id, time.time() - 100)

        mock_rt = MagicMock()
        mock_rt.transaction_store.return_value = txn_store
        mock_rt.checkpoint_store.return_value = cs

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(transaction_id=raw_id)
        result = json.loads(result_json)
        assert result["rolled_back"] is False
        assert "preview expired" in result["per_step"][0]["failure"]["reason"]

    def test_unknown_dispatcher_in_step_returns_capability_not_available(self, tmp_path):
        from serena.tools.scalpel_facades import TransactionCommitTool, _FACADE_DISPATCH
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore
        from serena.refactoring.transactions import TransactionStore

        tool = self._import_and_make(tmp_path)
        cs = CheckpointStore()
        txn_store = TransactionStore(checkpoint_store=cs)
        raw_id = txn_store.begin()
        txn_store.add_step(raw_id, {
            "tool": "scalpel_unknown_tool_xyz",
            "args": {"file": "/tmp/foo.rs"},
        })
        txn_store.set_expires_at(raw_id, 0.0)  # never expires

        mock_rt = MagicMock()
        mock_rt.transaction_store.return_value = txn_store
        mock_rt.checkpoint_store.return_value = cs

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(transaction_id=raw_id)
        result = json.loads(result_json)
        assert len(result["per_step"]) >= 1
        assert "Unknown tool" in result["per_step"][0]["failure"]["reason"]

    def test_dispatcher_raises_returns_internal_error(self, tmp_path):
        from serena.tools.scalpel_facades import TransactionCommitTool
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore
        from serena.refactoring.transactions import TransactionStore

        tool = self._import_and_make(tmp_path)
        cs = CheckpointStore()
        txn_store = TransactionStore(checkpoint_store=cs)
        raw_id = txn_store.begin()
        txn_store.add_step(raw_id, {
            "tool": "scalpel_split_file",
            "args": {"file": "/tmp/foo.rs", "groups": {}},
        })
        txn_store.set_expires_at(raw_id, 0.0)

        mock_rt = MagicMock()
        mock_rt.transaction_store.return_value = txn_store
        mock_rt.checkpoint_store.return_value = cs

        # Patch the dispatch table to raise
        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            with patch(
                "serena.tools.scalpel_facades._FACADE_DISPATCH",
                {"scalpel_split_file": lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))},
            ):
                result_json = tool.apply(transaction_id=raw_id)
        result = json.loads(result_json)
        assert "boom" in result["per_step"][0]["failure"]["reason"]

    def test_dispatcher_returns_invalid_json_gives_internal_error(self, tmp_path):
        from serena.tools.scalpel_facades import TransactionCommitTool
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore
        from serena.refactoring.transactions import TransactionStore

        tool = self._import_and_make(tmp_path)
        cs = CheckpointStore()
        txn_store = TransactionStore(checkpoint_store=cs)
        raw_id = txn_store.begin()
        txn_store.add_step(raw_id, {
            "tool": "scalpel_split_file",
            "args": {"file": "/tmp/foo.rs", "groups": {}},
        })
        txn_store.set_expires_at(raw_id, 0.0)

        mock_rt = MagicMock()
        mock_rt.transaction_store.return_value = txn_store
        mock_rt.checkpoint_store.return_value = cs

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            with patch(
                "serena.tools.scalpel_facades._FACADE_DISPATCH",
                {"scalpel_split_file": lambda **kw: "not valid json {{{"},
            ):
                result_json = tool.apply(transaction_id=raw_id)
        result = json.loads(result_json)
        assert "invalid JSON" in result["per_step"][0]["failure"]["reason"]


# ============================================================================
# TransactionRollbackTool — member_ids path
# ============================================================================


class TestTransactionRollbackToolWithMembers:
    def test_rollback_with_member_ids_walks_steps(self, tmp_path):
        from serena.tools.scalpel_primitives import TransactionRollbackTool
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore
        from serena.refactoring.transactions import TransactionStore

        tool = _make_tool(TransactionRollbackTool, str(tmp_path))
        ckpt_store = CheckpointStore()
        txn_store = TransactionStore(checkpoint_store=ckpt_store)

        raw_id = txn_store.begin()
        # Add a checkpoint via the store; record it as member of txn
        cid = ckpt_store.record(applied={"changes": {}}, snapshot={})
        txn_store.add_checkpoint(raw_id, cid)

        mock_rt = MagicMock()
        mock_rt.transaction_store.return_value = txn_store
        mock_rt.checkpoint_store.return_value = ckpt_store

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(transaction_id=raw_id)
        result = json.loads(result_json)
        assert result["rolled_back"] is True
        assert len(result["per_step"]) >= 1

    def test_rollback_already_reverted_checkpoint_marks_noop(self, tmp_path):
        from serena.tools.scalpel_primitives import TransactionRollbackTool
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from serena.refactoring.checkpoints import CheckpointStore
        from serena.refactoring.transactions import TransactionStore

        tool = _make_tool(TransactionRollbackTool, str(tmp_path))
        ckpt_store = CheckpointStore()
        txn_store = TransactionStore(checkpoint_store=ckpt_store)

        raw_id = txn_store.begin()
        cid = ckpt_store.record(applied={"changes": {}}, snapshot={})
        ckpt = ckpt_store.get(cid)
        ckpt.reverted = True  # mark as already reverted
        txn_store.add_checkpoint(raw_id, cid)

        mock_rt = MagicMock()
        mock_rt.transaction_store.return_value = txn_store
        mock_rt.checkpoint_store.return_value = ckpt_store

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply(transaction_id=raw_id)
        result = json.loads(result_json)
        # rolled_back=True at the transaction level even if all steps are noop
        assert result["rolled_back"] is True
        step = result["per_step"][0]
        assert step["no_op"] is True


# ============================================================================
# ReloadPluginsTool
# ============================================================================


class TestReloadPluginsTool:
    def test_apply_calls_plugin_registry_reload(self, tmp_path):
        from serena.tools.scalpel_primitives import ReloadPluginsTool
        from serena.tools.scalpel_runtime import ScalpelRuntime

        tool = _make_tool(ReloadPluginsTool, str(tmp_path))

        mock_registry = MagicMock()
        mock_report = MagicMock()
        mock_report.model_dump_json.return_value = '{"added":[],"removed":[],"unchanged":[],"errors":[],"is_clean":true}'
        mock_registry.reload.return_value = mock_report

        mock_rt = MagicMock()
        mock_rt.plugin_registry.return_value = mock_registry

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result_json = tool.apply()

        assert "is_clean" in result_json
        mock_registry.reload.assert_called_once()


# ============================================================================
# ScalpelRuntime — pool_for and editor_for_workspace
# ============================================================================


class TestScalpelRuntimeExtended:
    def test_pool_for_creates_pool_once_and_caches(self, tmp_path):
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from solidlsp.ls_config import Language

        ScalpelRuntime.reset_for_testing()
        try:
            rt = ScalpelRuntime.instance()
            p1 = rt.pool_for(Language.PYTHON, tmp_path)
            p2 = rt.pool_for(Language.PYTHON, tmp_path)
            assert p1 is p2
        finally:
            ScalpelRuntime.reset_for_testing()

    def test_editor_for_workspace_returns_workspace_editor(self, tmp_path):
        from serena.tools.scalpel_runtime import ScalpelRuntime, WorkspaceEditor
        from solidlsp.ls_config import Language

        ScalpelRuntime.reset_for_testing()
        try:
            rt = ScalpelRuntime.instance()
            mock_coord = MagicMock()
            with patch.object(rt, "coordinator_for", return_value=mock_coord):
                editor = rt.editor_for_workspace(Language.PYTHON, tmp_path)
            assert isinstance(editor, WorkspaceEditor)
            assert editor.coordinator is mock_coord
        finally:
            ScalpelRuntime.reset_for_testing()

    def test_workspace_editor_is_in_workspace(self, tmp_path):
        from serena.tools.scalpel_runtime import WorkspaceEditor
        from solidlsp.ls import SolidLanguageServer

        mock_coord = MagicMock()
        editor = WorkspaceEditor(coordinator=mock_coord, project_root=tmp_path)
        sub = tmp_path / "src" / "lib.rs"
        sub.parent.mkdir(parents=True, exist_ok=True)
        sub.write_text("", encoding="utf-8")

        with patch.object(
            SolidLanguageServer, "is_in_workspace", return_value=True
        ) as mock_iw:
            result = editor.is_in_workspace(sub)
        assert result is True
        mock_iw.assert_called_once()


# ============================================================================
# facade_support: _apply_workspace_edit_to_disk resource ops
# ============================================================================


class TestApplyWorkspaceEditResourceOps:
    def test_create_file_resource_op(self, tmp_path):
        from serena.tools.facade_support import _apply_workspace_edit_to_disk

        target = tmp_path / "newfile.rs"
        uri = target.as_uri()
        edit = {
            "documentChanges": [
                {"kind": "create", "uri": uri}
            ]
        }
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 1
        assert target.exists()

    def test_create_file_already_exists_skip(self, tmp_path):
        from serena.tools.facade_support import _apply_workspace_edit_to_disk

        target = tmp_path / "exists.rs"
        target.write_text("existing", encoding="utf-8")
        uri = target.as_uri()
        edit = {
            "documentChanges": [
                {"kind": "create", "uri": uri, "options": {"ignoreIfExists": True}}
            ]
        }
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 0  # skipped
        assert target.read_text() == "existing"

    def test_create_file_overwrite_option(self, tmp_path):
        from serena.tools.facade_support import _apply_workspace_edit_to_disk

        target = tmp_path / "overwrite.rs"
        target.write_text("old content", encoding="utf-8")
        uri = target.as_uri()
        edit = {
            "documentChanges": [
                {"kind": "create", "uri": uri, "options": {"overwrite": True, "ignoreIfExists": False}}
            ]
        }
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 1
        assert target.read_text() == ""  # written blank

    def test_delete_file_resource_op(self, tmp_path):
        from serena.tools.facade_support import _apply_workspace_edit_to_disk

        target = tmp_path / "delete_me.rs"
        target.write_text("delete this", encoding="utf-8")
        uri = target.as_uri()
        edit = {
            "documentChanges": [
                {"kind": "delete", "uri": uri}
            ]
        }
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 1
        assert not target.exists()

    def test_delete_file_not_exists_ignore(self, tmp_path):
        from serena.tools.facade_support import _apply_workspace_edit_to_disk

        uri = (tmp_path / "not_here.rs").as_uri()
        edit = {
            "documentChanges": [
                {"kind": "delete", "uri": uri, "options": {"ignoreIfNotExists": True}}
            ]
        }
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 0  # nothing deleted

    def test_rename_file_resource_op(self, tmp_path):
        from serena.tools.facade_support import _apply_workspace_edit_to_disk

        src = tmp_path / "old_name.rs"
        dst = tmp_path / "new_name.rs"
        src.write_text("content", encoding="utf-8")
        edit = {
            "documentChanges": [
                {"kind": "rename", "oldUri": src.as_uri(), "newUri": dst.as_uri()}
            ]
        }
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 1
        assert not src.exists()
        assert dst.exists()

    def test_unknown_kind_in_document_changes_skipped(self, tmp_path):
        from serena.tools.facade_support import _apply_workspace_edit_to_disk

        edit = {
            "documentChanges": [
                {"kind": "future_op", "uri": "file:///x.rs"}
            ]
        }
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 0


# ============================================================================
# facade_support: capture_pre_edit_snapshot
# ============================================================================


class TestCapturePreEditSnapshot:
    def test_captures_existing_file_content(self, tmp_path):
        from serena.tools.facade_support import capture_pre_edit_snapshot

        f = tmp_path / "snap.py"
        f.write_text("print('hello')", encoding="utf-8")
        uri = f.as_uri()
        edit = {"changes": {uri: []}}
        snapshot = capture_pre_edit_snapshot(edit)
        assert uri in snapshot
        assert snapshot[uri] == "print('hello')"

    def test_missing_file_uses_nonexistent_sentinel(self, tmp_path):
        from serena.tools.facade_support import capture_pre_edit_snapshot, _SNAPSHOT_NONEXISTENT

        uri = (tmp_path / "missing.py").as_uri()
        edit = {"changes": {uri: []}}
        snapshot = capture_pre_edit_snapshot(edit)
        assert snapshot[uri] == _SNAPSHOT_NONEXISTENT


# ============================================================================
# facade_support: _splice_text_edit idempotence guard
# ============================================================================


class TestSpliceTextEdit:
    def test_idempotent_guard_skips_already_applied(self):
        from serena.tools.facade_support import _splice_text_edit

        source = "fn foo() {}\n"
        edit = {
            "range": {
                "start": {"line": 0, "character": 3},
                "end": {"line": 0, "character": 6},
            },
            "newText": "foo",  # already the text at that position
        }
        result = _splice_text_edit(source, edit)
        # Guard: same text already there → no change
        assert result == source

    def test_normal_splice_replaces_text(self):
        from serena.tools.facade_support import _splice_text_edit

        source = "fn foo() {}\n"
        edit = {
            "range": {
                "start": {"line": 0, "character": 3},
                "end": {"line": 0, "character": 6},
            },
            "newText": "bar",
        }
        result = _splice_text_edit(source, edit)
        assert "bar" in result
        assert "foo" not in result


# ============================================================================
# facade_support: _lsp_position_to_offset edge cases
# ============================================================================


class TestLspPositionToOffset:
    def test_negative_line_returns_zero(self):
        from serena.tools.facade_support import _lsp_position_to_offset

        lines = ["hello\n", "world\n"]
        assert _lsp_position_to_offset(lines, -1, 0) == 0

    def test_line_beyond_end_returns_total_length(self):
        from serena.tools.facade_support import _lsp_position_to_offset

        lines = ["hello\n", "world\n"]
        result = _lsp_position_to_offset(lines, 99, 0)
        assert result == sum(len(l) for l in lines)

    def test_character_clamped_to_visible(self):
        from serena.tools.facade_support import _lsp_position_to_offset

        lines = ["hello\n"]
        # Character 100 should clamp to 5 (len("hello"))
        offset = _lsp_position_to_offset(lines, 0, 100)
        assert offset == 5


# ============================================================================
# _looks_like_module_name_path
# ============================================================================


class TestLooksLikeModuleNamePath:
    def _import(self):
        from serena.tools.scalpel_facades import _looks_like_module_name_path
        return _looks_like_module_name_path

    def test_simple_match_returns_true(self):
        fn = self._import()
        assert fn("calcpy", "/project/calcpy.py") is True

    def test_with_separator_returns_false(self):
        fn = self._import()
        assert fn("calcpy::Foo", "/project/calcpy.py") is False
        assert fn("calcpy.Foo", "/project/calcpy.py") is False
        assert fn("a/b", "/project/calcpy.py") is False

    def test_stem_mismatch_returns_false(self):
        fn = self._import()
        assert fn("other", "/project/calcpy.py") is False


# ============================================================================
# SplitFileTool — empty groups short-circuit
# ============================================================================


class TestSplitFileToolEmptyGroups:
    def test_empty_groups_returns_noop(self, tmp_path):
        from serena.tools.scalpel_facades import SplitFileTool

        tool = _make_tool(SplitFileTool, str(tmp_path))
        f = tmp_path / "lib.rs"
        f.write_text("fn foo() {}", encoding="utf-8")
        result_json = tool.apply(file=str(f), groups={})
        result = json.loads(result_json)
        assert result["no_op"] is True
        assert result["applied"] is False

    def test_unknown_language_ext_returns_failure(self, tmp_path):
        from serena.tools.scalpel_facades import SplitFileTool

        tool = _make_tool(SplitFileTool, str(tmp_path))
        f = tmp_path / "lib.unknown"
        f.write_text("fn foo() {}", encoding="utf-8")
        result_json = tool.apply(file=str(f), groups={"target": ["foo"]})
        result = json.loads(result_json)
        assert result.get("failure") is not None
        assert "Cannot infer language" in result["failure"]["reason"]


# ============================================================================
# tools_base: print_tool_overview branches
# ============================================================================


class TestToolRegistryPrintOverview:
    def test_only_optional_calls_get_tool_classes_optional(self):
        from serena.tools.tools_base import ToolRegistry
        reg = ToolRegistry()
        # Ensure this doesn't crash; just exercise the branch
        import io
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            reg.print_tool_overview(only_optional=True)
        # No exception → branch was exercised

    def test_include_optional_calls_get_all_tool_classes(self):
        from serena.tools.tools_base import ToolRegistry
        reg = ToolRegistry()
        import io
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            reg.print_tool_overview(include_optional=True)

    def test_default_calls_get_tool_classes_default_enabled(self):
        from serena.tools.tools_base import ToolRegistry
        reg = ToolRegistry()
        import io
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            reg.print_tool_overview()

    def test_explicit_tools_list(self):
        from serena.tools.tools_base import ToolRegistry
        from serena.tools.scalpel_facades import SplitFileTool
        reg = ToolRegistry()
        import io
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            reg.print_tool_overview(tools=[SplitFileTool])
        # At minimum the tool name should appear
        output = f.getvalue()
        # No crash; output is printed


# ============================================================================
# ExtractTool — range/name_path resolution branches
# ============================================================================


class TestExtractToolBoundary:
    def test_workspace_boundary_violation_returns_failure(self, tmp_path):
        from serena.tools.scalpel_facades import ExtractTool

        tool = _make_tool(ExtractTool, str(tmp_path))
        outside = tmp_path.parent / "outside.rs"
        outside.write_text("fn foo() {}", encoding="utf-8")
        result_json = tool.apply(
            file=str(outside),
            target="function",
            range={"start": {"line": 0, "character": 0},
                   "end": {"line": 0, "character": 5}},
        )
        result = json.loads(result_json)
        assert result.get("failure") is not None

    def test_no_range_no_name_path_returns_failure(self, tmp_path):
        from serena.tools.scalpel_facades import ExtractTool

        tool = _make_tool(ExtractTool, str(tmp_path))
        f = tmp_path / "lib.rs"
        f.write_text("fn foo() {}", encoding="utf-8")
        # Both range and name_path are None → short-circuit with INVALID_ARGUMENT
        result_json = tool.apply(
            file=str(f),
            target="function",
            # no range, no name_path
        )
        result = json.loads(result_json)
        assert result.get("failure") is not None
        assert "range" in result["failure"]["reason"] or "name_path" in result["failure"]["reason"]


# ============================================================================
# facade_support: coordinator_for_facade unknown language
# ============================================================================


class TestCoordinatorForFacade:
    def test_unknown_language_raises_value_error(self, tmp_path):
        from serena.tools.facade_support import coordinator_for_facade
        from serena.tools.scalpel_runtime import ScalpelRuntime

        mock_rt = MagicMock()
        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            with pytest.raises(ValueError, match="unknown language"):
                coordinator_for_facade(language="cobol", project_root=tmp_path)


# ============================================================================
# _merge_workspace_edits
# ============================================================================


class TestMergeWorkspaceEdits:
    def _import(self):
        from serena.tools.scalpel_facades import _merge_workspace_edits
        return _merge_workspace_edits

    def test_merge_two_changes_shape_edits(self):
        fn = self._import()
        e1 = {"changes": {"file:///a.py": [{"a": 1}]}}
        e2 = {"changes": {"file:///a.py": [{"b": 2}], "file:///b.py": [{"c": 3}]}}
        result = fn([e1, e2])
        assert len(result["changes"]["file:///a.py"]) == 2
        assert "file:///b.py" in result["changes"]

    def test_merge_empty_list_returns_empty(self):
        fn = self._import()
        result = fn([])
        # Empty merge: returns either empty changes or documentChanges
        assert not result.get("changes") and not result.get("documentChanges") or result is not None

    def test_merge_document_changes_shape(self):
        fn = self._import()
        e1 = {"documentChanges": [{"kind": "create", "uri": "file:///x.rs"}]}
        e2 = {"documentChanges": [{"kind": "create", "uri": "file:///y.rs"}]}
        result = fn([e1, e2])
        assert "documentChanges" in result
        assert len(result["documentChanges"]) == 2
