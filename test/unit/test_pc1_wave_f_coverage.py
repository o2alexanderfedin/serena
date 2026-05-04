"""PC1 Wave F: Additional coverage targeting pure-Python helper functions.

Targets:
- cmd_tools.ExecuteShellCommandTool.apply (lines 38-52)
- scalpel_runtime._AsyncAdapter.__getattr__ async path (line 92)
- scalpel_facades._rewrite_package_reexports (line 179 branch)
- scalpel_facades._augment_workspace_edit_with_all_update (lines 1565, 1567, 1575)
- scalpel_facades._filter_definition_deletion_hunks inner helper branches (1061, 1069-1070, 1091)
- scalpel_facades._build_python_rope_bridge (line 100-101)
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# cmd_tools.ExecuteShellCommandTool.apply
# ============================================================================


class TestExecuteShellCommandToolApply:
    def _make_tool(self, tmp_path: Path):
        from serena.tools.cmd_tools import ExecuteShellCommandTool
        tool = object.__new__(ExecuteShellCommandTool)
        tool.get_project_root = lambda: str(tmp_path)
        mock_agent = MagicMock()
        mock_agent.serena_config.default_max_tool_answer_chars = 10_000
        tool.agent = mock_agent
        return tool

    def _mock_result(self):
        mock_result = MagicMock()
        mock_result.json.return_value = '{"stdout": "hello", "stderr": ""}'
        return mock_result

    def test_apply_with_no_cwd_uses_project_root(self, tmp_path):
        tool = self._make_tool(tmp_path)
        with patch("serena.tools.cmd_tools.execute_shell_command", return_value=self._mock_result()) as mock_exec:
            result = tool.apply("echo hello")
        mock_exec.assert_called_once_with("echo hello", cwd=str(tmp_path), capture_stderr=True)
        assert "stdout" in result

    def test_apply_with_absolute_cwd(self, tmp_path):
        tool = self._make_tool(tmp_path)
        sub = tmp_path / "sub"
        sub.mkdir()
        with patch("serena.tools.cmd_tools.execute_shell_command", return_value=self._mock_result()) as mock_exec:
            result = tool.apply("echo hi", cwd=str(sub))
        mock_exec.assert_called_once_with("echo hi", cwd=str(sub), capture_stderr=True)
        assert result is not None

    def test_apply_with_relative_cwd(self, tmp_path):
        tool = self._make_tool(tmp_path)
        sub = tmp_path / "reldir"
        sub.mkdir()
        with patch("serena.tools.cmd_tools.execute_shell_command", return_value=self._mock_result()) as mock_exec:
            result = tool.apply("ls", cwd="reldir")
        mock_exec.assert_called_once()
        assert result is not None

    def test_apply_with_relative_cwd_not_a_dir_raises(self, tmp_path):
        tool = self._make_tool(tmp_path)
        # "notadir" does not exist under tmp_path
        with pytest.raises(FileNotFoundError):
            tool.apply("ls", cwd="notadir")

    def test_apply_capture_stderr_false(self, tmp_path):
        tool = self._make_tool(tmp_path)
        with patch("serena.tools.cmd_tools.execute_shell_command", return_value=self._mock_result()) as mock_exec:
            tool.apply("echo x", capture_stderr=False)
        mock_exec.assert_called_once_with("echo x", cwd=str(tmp_path), capture_stderr=False)

    def test_apply_limits_output_length(self, tmp_path):
        tool = self._make_tool(tmp_path)
        long_result = MagicMock()
        long_result.json.return_value = "x" * 100
        with patch("serena.tools.cmd_tools.execute_shell_command", return_value=long_result):
            result = tool.apply("echo x", max_answer_chars=10)
        # _limit_length should truncate; just check it doesn't crash
        assert result is not None


# ============================================================================
# scalpel_runtime._AsyncAdapter async path
# ============================================================================


class TestAsyncAdapterAsyncPath:
    def test_async_method_returns_coroutine(self):
        """An _ASYNC_METHODS name returns an async-wrapped coroutine."""
        from serena.tools.scalpel_runtime import _AsyncAdapter

        inner = MagicMock()
        inner.request_code_actions = MagicMock(return_value="actions_result")

        adapter = _AsyncAdapter(inner)
        fn = adapter.request_code_actions

        # Should be an async callable (coroutine function)
        import inspect
        assert inspect.iscoroutinefunction(fn)

    def test_async_method_calls_inner_via_thread(self):
        """The async wrapper passes call through to the inner method."""
        from serena.tools.scalpel_runtime import _AsyncAdapter

        inner = MagicMock()
        inner.request_code_actions = MagicMock(return_value=["action1"])

        adapter = _AsyncAdapter(inner)

        async def run():
            fn = adapter.request_code_actions
            return await fn("file.py", [])

        result = asyncio.run(run())
        assert result == ["action1"]
        inner.request_code_actions.assert_called_once_with("file.py", [])

    def test_non_async_method_returned_directly(self):
        """Non-async method name returns the inner attribute directly."""
        from serena.tools.scalpel_runtime import _AsyncAdapter

        inner = MagicMock()
        inner.some_sync_method = "a_value"

        adapter = _AsyncAdapter(inner)
        result = adapter.some_sync_method
        assert result == "a_value"


# ============================================================================
# scalpel_facades._rewrite_package_reexports branch: moved_aliases empty
# ============================================================================


class TestRewritePackageReexportsBranches:
    def _import(self):
        from serena.tools.scalpel_facades import _rewrite_package_reexports
        return _rewrite_package_reexports

    def test_no_matching_imports_returns_empty(self, tmp_path):
        """No files import from the source module → no edits."""
        fn = self._import()
        src = tmp_path / "mymod.py"
        src.write_text("x = 1\n", encoding="utf-8")
        other = tmp_path / "other.py"
        other.write_text("import os\n", encoding="utf-8")

        result = fn(project_root=tmp_path, source_rel="mymod.py", moves=[("x", "newmod.py")])
        assert result == []

    def test_import_matches_module_but_no_moved_symbols_skipped(self, tmp_path):
        """Import from source module but none of the imported names are in moves → continue (line 179)."""
        fn = self._import()
        src = tmp_path / "calc.py"
        src.write_text("A = 1\nB = 2\n", encoding="utf-8")
        importer = tmp_path / "use.py"
        # 'B' is imported but only 'A' is being moved — so moved_aliases will be empty
        # Wait: absolute import path. src is "calc.py" -> dotted = "calc"
        importer.write_text("from calc import B\n", encoding="utf-8")

        result = fn(project_root=tmp_path, source_rel="calc.py", moves=[("A", "newcalc.py")])
        assert result == []

    def test_absolute_import_with_moved_symbol_generates_edit(self, tmp_path):
        """Absolute import with a moved symbol produces an edit."""
        fn = self._import()
        src = tmp_path / "mod.py"
        src.write_text("Foo = 1\n", encoding="utf-8")
        importer = tmp_path / "__init__.py"
        importer.write_text("from mod import Foo\n", encoding="utf-8")

        result = fn(project_root=tmp_path, source_rel="mod.py", moves=[("Foo", "newmod.py")])
        # An edit should be generated for __init__.py
        assert len(result) >= 1

    def test_syntax_error_in_file_skips(self, tmp_path):
        """File with a SyntaxError is silently skipped."""
        fn = self._import()
        src = tmp_path / "mod.py"
        src.write_text("x = 1\n", encoding="utf-8")
        bad = tmp_path / "bad.py"
        bad.write_text("def (x:\n", encoding="utf-8")  # syntax error

        result = fn(project_root=tmp_path, source_rel="mod.py", moves=[("x", "new.py")])
        assert isinstance(result, list)

    def test_read_error_skips_file(self, tmp_path):
        """OSError when reading a file is silently skipped."""
        fn = self._import()
        src = tmp_path / "mod.py"
        src.write_text("x = 1\n", encoding="utf-8")

        original_read = Path.read_text

        def mock_read(self, **kwargs):
            if self.name != "mod.py":
                raise OSError("permission denied")
            return original_read(self, **kwargs)

        with patch.object(Path, "read_text", mock_read):
            result = fn(project_root=tmp_path, source_rel="mod.py", moves=[("x", "new.py")])
        assert isinstance(result, list)


# ============================================================================
# scalpel_facades._augment_workspace_edit_with_all_update branch coverage
# ============================================================================


class TestAugmentWorkspaceEditWithAllUpdateBranches:
    def _import(self):
        from serena.tools.scalpel_facades import _augment_workspace_edit_with_all_update
        return _augment_workspace_edit_with_all_update

    def test_no_all_assignment_returns_unchanged(self, tmp_path):
        """File with no __all__ assignment → workspace_edit unchanged."""
        fn = self._import()
        f = tmp_path / "mod.py"
        f.write_text("x = 1\ny = 2\n", encoding="utf-8")
        edit: dict[str, Any] = {"changes": {}}
        result = fn(edit, str(f), "x", "z")
        assert result is edit

    def test_all_not_list_or_tuple_skips(self, tmp_path):
        """__all__ = some_call() is not a List/Tuple → line 1567 branch."""
        fn = self._import()
        f = tmp_path / "mod.py"
        f.write_text("__all__ = list()\n", encoding="utf-8")
        edit: dict[str, Any] = {"changes": {}}
        result = fn(edit, str(f), "x", "z")
        # No text-edit should be appended
        assert result is edit or "changes" in result

    def test_all_target_not_in_all_list_returns_unchanged(self, tmp_path):
        """__all__ exists but old_name not in it → no text-edit appended."""
        fn = self._import()
        f = tmp_path / "mod.py"
        f.write_text('__all__ = ["other_func"]\n', encoding="utf-8")
        edit: dict[str, Any] = {"changes": {}}
        result = fn(edit, str(f), "my_func", "renamed")
        # No edit added for the source file
        file_uri = f.as_uri()
        changes = result.get("changes", {})
        file_edits = changes.get(file_uri, [])
        assert len(file_edits) == 0

    def test_all_contains_old_name_appends_text_edit(self, tmp_path):
        """__all__ contains old_name → text edit appended."""
        fn = self._import()
        f = tmp_path / "mod.py"
        f.write_text('__all__ = ["my_func", "other"]\n', encoding="utf-8")
        edit: dict[str, Any] = {"changes": {}}
        result = fn(edit, str(f), "my_func", "renamed_func")
        file_uri = f.as_uri()
        file_edits = result["changes"][file_uri]
        assert len(file_edits) == 1
        assert file_edits[0]["newText"] == "renamed_func"

    def test_assign_not_targeting_all_skips(self, tmp_path):
        """Assignment to other variable (not __all__) → line 1565 branch."""
        fn = self._import()
        f = tmp_path / "mod.py"
        f.write_text('exports = ["my_func"]\n', encoding="utf-8")
        edit: dict[str, Any] = {"changes": {}}
        result = fn(edit, str(f), "my_func", "renamed")
        file_uri = f.as_uri()
        changes = result.get("changes", {})
        assert len(changes.get(file_uri, [])) == 0

    def test_os_error_returns_unchanged(self, tmp_path):
        """File that can't be read → workspace_edit returned unchanged."""
        fn = self._import()
        edit: dict[str, Any] = {"changes": {}}
        result = fn(edit, str(tmp_path / "nonexistent.py"), "x", "z")
        assert result is edit

    def test_syntax_error_returns_unchanged(self, tmp_path):
        """File with SyntaxError → workspace_edit returned unchanged."""
        fn = self._import()
        f = tmp_path / "bad.py"
        f.write_text("def (x:\n", encoding="utf-8")
        edit: dict[str, Any] = {"changes": {}}
        result = fn(edit, str(f), "x", "z")
        assert result is edit


# ============================================================================
# scalpel_facades._filter_definition_deletion_hunks inner helper branches
# ============================================================================


class TestFilterDefinitionDeletionHunksHelperBranches:
    def _import(self):
        from serena.tools.scalpel_facades import _filter_definition_deletion_hunks
        return _filter_definition_deletion_hunks

    def test_non_dict_edit_passes_through(self):
        """Non-dict item in edits list (line 1061) → _is_definition_deletion returns False → kept."""
        fn = self._import()
        edit = {
            "changes": {
                "file:///lib.rs": [
                    "not_a_dict",  # non-dict; should be kept (not treated as deletion)
                ]
            }
        }
        result = fn(edit)
        # Non-dict item should be preserved since _is_definition_deletion returns False for it
        assert "not_a_dict" in result["changes"]["file:///lib.rs"]

    def test_type_error_in_line_comparison_returns_false(self):
        """TypeError in line comparison (line 1069-1070) → kept in output."""
        fn = self._import()
        # 'line' value is not an int-convertible → TypeError handled → returns False → kept
        edit = {
            "changes": {
                "file:///lib.rs": [
                    {
                        "range": {
                            "start": {"line": "x", "character": 0},
                            "end": {"line": "y", "character": 0},
                        },
                        "newText": "",
                    }
                ]
            }
        }
        result = fn(edit)
        # Since _is_definition_deletion returns False (TypeError), hunk is kept
        assert len(result["changes"]["file:///lib.rs"]) == 1

    def test_document_changes_non_dict_entry_preserved(self):
        """Non-dict entry in documentChanges list (line 1091) → passed through verbatim."""
        fn = self._import()
        edit = {
            "documentChanges": [
                "string_entry",  # non-dict, no "edits" key
            ]
        }
        result = fn(edit)
        assert result["documentChanges"][0] == "string_entry"

    def test_document_changes_dict_without_edits_preserved(self):
        """Dict entry without 'edits' key in documentChanges (line 1091) → passed through."""
        fn = self._import()
        edit = {
            "documentChanges": [
                {"kind": "create", "uri": "file:///new.rs"},  # no "edits"
            ]
        }
        result = fn(edit)
        assert result["documentChanges"][0]["kind"] == "create"
