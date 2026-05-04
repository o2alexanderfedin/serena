"""PC3 Wave 2 — targeted coverage for:
  - file_tools.py: ReadFileTool, CreateTextFileTool, ListDirTool, FindFileTool,
    SearchForPatternTool, ReplaceContentTool branches
  - memory_tools.py: WriteMemoryTool length guard, ReadMemoryTool, ListMemoriesTool,
    DeleteMemoryTool, RenameMemoryTool, EditMemoryTool
  - config_tools.py: ActivateProjectTool, RemoveProjectTool, GetCurrentConfigTool,
    OpenDashboardTool
  - tools_base.py: create_language_server_symbol_retriever, additional paths
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _make_project_mock(tmp_path: Path, *, files: dict[str, str] | None = None) -> MagicMock:
    """Create a minimal project mock with a real temp directory."""
    project = MagicMock()
    project.project_root = str(tmp_path)
    project.project_config.encoding = "utf-8"
    from serena.config.serena_config import LineEnding
    project.line_ending = LineEnding.LF

    # write real files if specified
    if files:
        for rel, content in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

    def _read_file(rel_path: str) -> str:
        return (tmp_path / rel_path).read_text(encoding="utf-8")

    def _rel_exists(rel_path: str) -> bool:
        return (tmp_path / rel_path).exists()

    def _is_ignored(p: str) -> bool:
        return False

    def _validate(rel_path: str, require_not_ignored: bool = True) -> None:
        pass

    project.read_file.side_effect = _read_file
    project.relative_path_exists.side_effect = _rel_exists
    project.is_ignored_path.side_effect = _is_ignored
    project.validate_relative_path.side_effect = _validate
    return project


def _make_agent_with_project(tmp_path: Path, **file_kwargs) -> MagicMock:
    """Return an agent whose active project is backed by tmp_path."""
    project = _make_project_mock(tmp_path, **file_kwargs)
    agent = MagicMock()
    agent.get_active_project.return_value = project
    agent.get_active_project_or_raise.return_value = project
    return agent


# ===========================================================================
# file_tools.py
# ===========================================================================

class TestReadFileTool:
    """Tests for ReadFileTool.apply."""

    def _make_tool(self, tmp_path: Path, files: dict[str, str]) -> Any:
        from serena.tools.file_tools import ReadFileTool

        tool = object.__new__(ReadFileTool)
        tool.agent = _make_agent_with_project(tmp_path, files=files)

        def _limit(s, max_c, **kw):
            return s
        tool._limit_length = _limit
        return tool

    def test_read_full_file(self, tmp_path):
        """Read entire file returns all content."""
        tool = self._make_tool(tmp_path, {"test.txt": "line1\nline2\nline3"})
        result = tool.apply("test.txt")
        assert "line1" in result
        assert "line3" in result

    def test_read_with_start_and_end_line(self, tmp_path):
        """Read with start_line/end_line returns only those lines."""
        tool = self._make_tool(tmp_path, {"test.txt": "line0\nline1\nline2\nline3"})
        result = tool.apply("test.txt", start_line=1, end_line=2)
        assert "line1" in result
        assert "line2" in result
        # line0 and line3 not included
        assert "line0" not in result
        assert "line3" not in result

    def test_read_from_start_line_to_end(self, tmp_path):
        """Read from start_line to end of file (no end_line)."""
        tool = self._make_tool(tmp_path, {"test.txt": "a\nb\nc"})
        result = tool.apply("test.txt", start_line=1)
        assert "b" in result
        assert "c" in result
        assert result.startswith("b")


class TestCreateTextFileTool:
    """Tests for CreateTextFileTool.apply."""

    def _make_tool(self, tmp_path: Path) -> Any:
        from serena.tools.file_tools import CreateTextFileTool

        tool = object.__new__(CreateTextFileTool)
        tool.agent = _make_agent_with_project(tmp_path)
        # get_project_root returns tmp_path
        tool.get_project_root = lambda: str(tmp_path)
        return tool

    def test_create_new_file(self, tmp_path):
        """Creating a new file writes content and returns success."""
        tool = self._make_tool(tmp_path)
        result = tool.apply("new_file.txt", "hello world")
        assert "created" in result.lower() or "File" in result
        assert (tmp_path / "new_file.txt").read_text() == "hello world"

    def test_overwrite_existing_file(self, tmp_path):
        """Overwriting an existing file returns appropriate message."""
        existing = tmp_path / "existing.txt"
        existing.write_text("old content")
        tool = self._make_tool(tmp_path)
        result = tool.apply("existing.txt", "new content")
        assert "Overwrote" in result or "overwrite" in result.lower() or "File created" in result
        assert (tmp_path / "existing.txt").read_text() == "new content"

    def test_create_file_outside_project_raises(self, tmp_path):
        """Creating a file outside project root raises AssertionError."""
        tool = self._make_tool(tmp_path)
        with pytest.raises((AssertionError, ValueError, Exception)):
            tool.apply("../../outside.txt", "bad content")


class TestListDirTool:
    """Tests for ListDirTool.apply."""

    def _make_tool(self, tmp_path: Path) -> Any:
        from serena.tools.file_tools import ListDirTool

        tool = object.__new__(ListDirTool)
        tool.agent = _make_agent_with_project(tmp_path)
        tool.get_project_root = lambda: str(tmp_path)

        def _limit(s, max_c, **kw):
            return s
        tool._limit_length = _limit
        tool._to_json = json.dumps
        return tool

    def test_list_existing_directory(self, tmp_path):
        """Listing an existing directory returns JSON with dirs and files."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file.txt").write_text("content")
        tool = self._make_tool(tmp_path)
        result = tool.apply(".", recursive=False)
        data = json.loads(result)
        assert "files" in data
        assert "dirs" in data

    def test_list_nonexistent_directory_returns_error(self, tmp_path):
        """Listing a non-existent path returns error JSON."""
        tool = self._make_tool(tmp_path)
        result = tool.apply("nonexistent/dir", recursive=False)
        data = json.loads(result)
        assert "error" in data


class TestFindFileTool:
    """Tests for FindFileTool.apply."""

    def _make_tool(self, tmp_path: Path) -> Any:
        from serena.tools.file_tools import FindFileTool

        tool = object.__new__(FindFileTool)
        tool.agent = _make_agent_with_project(tmp_path)
        tool.get_project_root = lambda: str(tmp_path)
        tool._to_json = json.dumps
        return tool

    def test_find_files_by_mask(self, tmp_path):
        """FindFileTool finds matching files."""
        (tmp_path / "hello.py").write_text("pass")
        (tmp_path / "world.txt").write_text("text")
        tool = self._make_tool(tmp_path)
        result = tool.apply("*.py", ".")
        data = json.loads(result)
        assert "files" in data
        assert any("hello.py" in f for f in data["files"])
        assert not any("world.txt" in f for f in data["files"])


class TestSearchForPatternTool:
    """Tests for SearchForPatternTool.apply."""

    def _make_tool(self, tmp_path: Path) -> Any:
        from serena.tools.file_tools import SearchForPatternTool

        tool = object.__new__(SearchForPatternTool)
        project = _make_project_mock(tmp_path, files={"code.py": "def foo():\n    pass\n\ndef bar():\n    return 42\n"})
        agent = MagicMock()
        agent.get_active_project.return_value = project
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        tool.get_project_root = lambda: str(tmp_path)

        def _limit(s, max_c, **kw):
            return s
        tool._limit_length = _limit
        tool._to_json = json.dumps
        return tool

    def test_search_finds_matches(self, tmp_path):
        """SearchForPatternTool finds pattern in files."""
        tool = self._make_tool(tmp_path)
        result = tool.apply("def foo", relative_path="code.py")
        assert "foo" in result

    def test_search_nonexistent_path_raises(self, tmp_path):
        """SearchForPatternTool raises FileNotFoundError for nonexistent path."""
        tool = self._make_tool(tmp_path)
        with pytest.raises(FileNotFoundError):
            tool.apply("pattern", relative_path="nonexistent_file.py")


# ===========================================================================
# memory_tools.py
# ===========================================================================

class TestWriteMemoryTool:
    """Tests for WriteMemoryTool."""

    def _make_tool(self, max_chars: int = 1000) -> Any:
        from serena.tools.memory_tools import WriteMemoryTool

        tool = object.__new__(WriteMemoryTool)
        agent = MagicMock()
        agent.serena_config.default_max_tool_answer_chars = max_chars
        mm = MagicMock()
        mm.save_memory.return_value = "saved"
        project = MagicMock()
        project.memories_manager = mm
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        return tool

    def test_save_within_limit(self):
        """Content within limit is saved."""
        tool = self._make_tool(max_chars=1000)
        result = tool.apply("my_memory", "short content")
        assert result == "saved"

    def test_save_exceeds_limit_raises(self):
        """Content exceeding limit raises ValueError."""
        tool = self._make_tool(max_chars=10)
        with pytest.raises(ValueError, match="too long"):
            tool.apply("my_memory", "this is much longer than 10 characters")

    def test_explicit_max_chars_used(self):
        """Explicit max_chars overrides default."""
        tool = self._make_tool(max_chars=1000)
        # Pass explicit max_chars of 5 — should raise for content > 5 chars
        with pytest.raises(ValueError):
            tool.apply("my_memory", "hello world", max_chars=5)


class TestReadMemoryTool:
    """Tests for ReadMemoryTool."""

    def _make_tool(self) -> Any:
        from serena.tools.memory_tools import ReadMemoryTool

        tool = object.__new__(ReadMemoryTool)
        agent = MagicMock()
        mm = MagicMock()
        mm.load_memory.return_value = "memory content"
        project = MagicMock()
        project.memories_manager = mm
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        return tool

    def test_load_memory_returns_content(self):
        """ReadMemoryTool returns loaded memory content."""
        tool = self._make_tool()
        result = tool.apply("some_memory")
        assert result == "memory content"


class TestListMemoriesTool:
    """Tests for ListMemoriesTool."""

    def _make_tool(self) -> Any:
        from serena.tools.memory_tools import ListMemoriesTool

        tool = object.__new__(ListMemoriesTool)
        agent = MagicMock()
        mm = MagicMock()
        mem_list = MagicMock()
        mem_list.to_dict.return_value = {"memories": ["mem1", "mem2"]}
        mm.list_memories.return_value = mem_list
        project = MagicMock()
        project.memories_manager = mm
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        tool._to_json = json.dumps
        return tool

    def test_list_memories_returns_json(self):
        """ListMemoriesTool returns JSON with memories."""
        tool = self._make_tool()
        result = tool.apply(topic="")
        data = json.loads(result)
        assert "memories" in data


class TestDeleteMemoryTool:
    """Tests for DeleteMemoryTool."""

    def _make_tool(self) -> Any:
        from serena.tools.memory_tools import DeleteMemoryTool

        tool = object.__new__(DeleteMemoryTool)
        agent = MagicMock()
        mm = MagicMock()
        mm.delete_memory.return_value = "deleted"
        project = MagicMock()
        project.memories_manager = mm
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        return tool

    def test_delete_memory(self):
        """DeleteMemoryTool calls delete_memory."""
        tool = self._make_tool()
        result = tool.apply("my_memory")
        assert result == "deleted"


class TestRenameMemoryTool:
    """Tests for RenameMemoryTool."""

    def _make_tool(self) -> Any:
        from serena.tools.memory_tools import RenameMemoryTool

        tool = object.__new__(RenameMemoryTool)
        agent = MagicMock()
        mm = MagicMock()
        mm.move_memory.return_value = "moved"
        project = MagicMock()
        project.memories_manager = mm
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        return tool

    def test_rename_memory(self):
        """RenameMemoryTool calls move_memory."""
        tool = self._make_tool()
        result = tool.apply("old_name", "new_name")
        assert result == "moved"


class TestEditMemoryTool:
    """Tests for EditMemoryTool."""

    def _make_tool(self) -> Any:
        from serena.tools.memory_tools import EditMemoryTool

        tool = object.__new__(EditMemoryTool)
        agent = MagicMock()
        mm = MagicMock()
        mm.edit_memory.return_value = "edited"
        project = MagicMock()
        project.memories_manager = mm
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        return tool

    def test_edit_memory_literal(self):
        """EditMemoryTool calls edit_memory with literal mode."""
        tool = self._make_tool()
        result = tool.apply("mem", "old", "new", "literal")
        assert result == "edited"

    def test_edit_memory_regex(self):
        """EditMemoryTool calls edit_memory with regex mode."""
        tool = self._make_tool()
        result = tool.apply("mem", r"\bfoo\b", "bar", "regex", allow_multiple_occurrences=True)
        assert result == "edited"


# ===========================================================================
# config_tools.py
# ===========================================================================

class TestOpenDashboardTool:
    """Tests for OpenDashboardTool."""

    def _make_tool(self, open_succeeds: bool = True) -> Any:
        from serena.tools.config_tools import OpenDashboardTool

        tool = object.__new__(OpenDashboardTool)
        agent = MagicMock()
        agent.open_dashboard.return_value = open_succeeds
        agent.get_dashboard_url.return_value = "http://localhost:8888"
        tool.agent = agent
        return tool

    def test_open_succeeds(self):
        """When dashboard opens, returns success message with URL."""
        tool = self._make_tool(open_succeeds=True)
        result = tool.apply()
        assert "http://localhost:8888" in result
        assert "opened" in result.lower()

    def test_open_fails(self):
        """When dashboard cannot open, returns manual URL message."""
        tool = self._make_tool(open_succeeds=False)
        result = tool.apply()
        assert "http://localhost:8888" in result
        assert "could not" in result.lower() or "automatically" in result.lower()


class TestActivateProjectTool:
    """Tests for ActivateProjectTool."""

    def _make_tool(self) -> Any:
        from serena.tools.config_tools import ActivateProjectTool

        tool = object.__new__(ActivateProjectTool)
        agent = MagicMock()
        agent.activate_project_from_path_or_name.return_value = True
        agent.get_project_activation_message.return_value = "Activated!"
        tool.agent = agent
        return tool

    def test_activate_project(self):
        """ActivateProjectTool activates project and returns activation message."""
        tool = self._make_tool()
        result = tool.apply("my_project", session_id="test_session")
        assert "Activated!" in result
        assert "Scalpel Tool Manual" in result


class TestRemoveProjectTool:
    """Tests for RemoveProjectTool."""

    def _make_tool(self) -> Any:
        from serena.tools.config_tools import RemoveProjectTool

        tool = object.__new__(RemoveProjectTool)
        agent = MagicMock()
        agent.serena_config.remove_project.return_value = None
        tool.agent = agent
        return tool

    def test_remove_project(self):
        """RemoveProjectTool removes project and returns success message."""
        tool = self._make_tool()
        result = tool.apply("my_project")
        assert "my_project" in result
        tool.agent.serena_config.remove_project.assert_called_once_with("my_project")


class TestGetCurrentConfigTool:
    """Tests for GetCurrentConfigTool."""

    def _make_tool(self) -> Any:
        from serena.tools.config_tools import GetCurrentConfigTool

        tool = object.__new__(GetCurrentConfigTool)
        agent = MagicMock()
        agent.get_current_config_overview.return_value = "config_overview"
        tool.agent = agent
        return tool

    def test_get_current_config(self):
        """GetCurrentConfigTool returns config overview."""
        tool = self._make_tool()
        result = tool.apply()
        assert result == "config_overview"


# ===========================================================================
# tools_base.py — create_language_server_symbol_retriever
# ===========================================================================

class TestCreateLsSymbolRetriever:
    """Tests for Component.create_language_server_symbol_retriever."""

    def _make_tool(self, lsp_backend: bool = True) -> Any:
        from serena.tools.tools_base import Tool

        class _T(Tool):
            def apply(self) -> str:
                """Apply."""
                return "ok"

        tool = object.__new__(_T)
        agent = MagicMock()
        backend_mock = MagicMock()
        backend_mock.is_lsp.return_value = lsp_backend
        agent.get_language_backend.return_value = backend_mock
        project = MagicMock()
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        return tool

    def test_non_lsp_backend_raises_assertion(self):
        """create_language_server_symbol_retriever raises for non-LSP backend."""
        tool = self._make_tool(lsp_backend=False)
        with pytest.raises((AssertionError, Exception)):
            tool.create_language_server_symbol_retriever()

    def test_lsp_backend_creates_retriever(self):
        """create_language_server_symbol_retriever works for LSP backend."""
        tool = self._make_tool(lsp_backend=True)
        with patch("serena.symbol.LanguageServerSymbolRetriever") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = tool.create_language_server_symbol_retriever()
            assert result is not None
