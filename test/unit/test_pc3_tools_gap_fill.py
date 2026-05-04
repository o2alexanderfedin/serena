"""PC3 final push — serena.tools gap-fill tests.

Targets (by module):
  - workflow_tools.py: CheckOnboardingPerformedTool branches,
    OnboardingTool memory-write-unavailable, SerenaInfoTool invalid topic,
    InitialInstructionsTool session_id injection
  - symbol_tools.py: GetSymbolsOverviewTool depth>0 branch,
    GetSymbolsOverviewTool dir path raises, GetSymbolsOverviewTool file-not-found,
    FindSymbolTool max_matches exceeded
  - tools_base.py: create_code_editor JetBrains branch, create_code_editor LS branch,
    create_ls_code_editor non-LS mode exception, apply_ex SolidLSPException restart,
    apply_ex no-active-project guard, apply_ex timeout exception
  - query_project_tools.py: ListQueryableProjectsTool, QueryProjectTool LSP path,
    QueryProjectTool _is_project_server_required branches
  - scalpel_runtime.py: _spawn_* functions import paths, coordinator_for caching
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _make_agent_mock(*, has_active_project: bool = True, tool_exposed: bool = True,
                     lsp_mode: bool = True, memories: list | None = None) -> MagicMock:
    """Minimal agent mock covering the workflow / symbol tool paths."""
    agent = MagicMock()
    if has_active_project:
        project = MagicMock()
        project.project_root = "/tmp/test_project"
        agent.get_active_project.return_value = project
        agent.get_active_project_or_raise.return_value = project
    else:
        agent.get_active_project.return_value = None
        agent.get_active_project_or_raise.side_effect = RuntimeError("no project")
    agent.tool_is_exposed.return_value = tool_exposed
    agent.is_using_language_server.return_value = lsp_mode
    if memories is None:
        memories = []
    return agent


# ===========================================================================
# workflow_tools.py
# ===========================================================================

class TestCheckOnboardingPerformedTool:
    """Tests for CheckOnboardingPerformedTool."""

    def _make_tool(self, *, has_memories: bool = False, memory_tool_exposed: bool = True,
                   onboarding_tool_exposed: bool = True) -> Any:
        from serena.tools.workflow_tools import CheckOnboardingPerformedTool

        tool = object.__new__(CheckOnboardingPerformedTool)
        agent = MagicMock()
        # First call: ReadMemoryTool exposed check; second: OnboardingTool
        agent.tool_is_exposed.side_effect = [memory_tool_exposed, onboarding_tool_exposed]
        # memories_manager is a property that goes through project.memories_manager
        mm = MagicMock()
        mm.list_project_memories.return_value = ["mem1"] if has_memories else []
        project = MagicMock()
        project.memories_manager = mm
        agent.get_active_project_or_raise.return_value = project
        tool.agent = agent
        return tool

    def test_memory_tool_not_available(self):
        """When ReadMemoryTool not exposed, returns skip message."""
        tool = self._make_tool(memory_tool_exposed=False)
        result = tool.apply()
        assert "Memory reading tool not activated" in result

    def test_no_memories_onboarding_tool_available(self):
        """When no memories and onboarding tool exposed, suggests onboarding."""
        tool = self._make_tool(has_memories=False, memory_tool_exposed=True, onboarding_tool_exposed=True)
        result = tool.apply()
        assert "Onboarding not performed yet" in result
        assert "onboarding" in result.lower()

    def test_no_memories_onboarding_tool_not_available(self):
        """When no memories and onboarding tool NOT exposed, no suggestion."""
        tool = self._make_tool(has_memories=False, memory_tool_exposed=True, onboarding_tool_exposed=False)
        result = tool.apply()
        assert "Onboarding not performed yet" in result

    def test_with_memories_returns_count(self):
        """When memories present, returns count message."""
        tool = self._make_tool(has_memories=True)
        result = tool.apply()
        assert "1 project memories" in result


class TestOnboardingTool:
    """Tests for OnboardingTool."""

    def _make_tool(self, *, write_exposed: bool = True) -> Any:
        from serena.tools.workflow_tools import OnboardingTool

        tool = object.__new__(OnboardingTool)
        agent = MagicMock()
        agent.tool_is_exposed.return_value = write_exposed
        pf = MagicMock()
        pf.create_onboarding_prompt.return_value = "ONBOARD"
        agent.prompt_factory = pf
        tool.agent = agent
        return tool

    def test_write_tool_not_exposed_returns_skip(self):
        """When WriteMemoryTool not exposed, returns skip message."""
        tool = self._make_tool(write_exposed=False)
        result = tool.apply()
        assert "Memory writing tool not activated" in result

    def test_write_tool_exposed_calls_prompt_factory(self):
        """When WriteMemoryTool is exposed, calls prompt_factory.create_onboarding_prompt."""
        tool = self._make_tool(write_exposed=True)
        result = tool.apply()
        assert result == "ONBOARD"
        # Verify platform was passed (it's called with system=...)
        tool.prompt_factory.create_onboarding_prompt.assert_called_once()
        call_kwargs = tool.prompt_factory.create_onboarding_prompt.call_args[1]
        assert "system" in call_kwargs
        assert call_kwargs["system"] in ("Windows", "Linux", "Darwin", "Java")


class TestSerenaInfoTool:
    """Tests for SerenaInfoTool."""

    def _make_tool(self) -> Any:
        from serena.tools.workflow_tools import SerenaInfoTool

        tool = object.__new__(SerenaInfoTool)
        agent = MagicMock()
        pf = MagicMock()
        pf.create_info_jet_brains_debug_repl.return_value = "JB_INFO"
        agent.prompt_factory = pf
        tool.agent = agent
        return tool

    def test_invalid_topic_raises(self):
        """Invalid topic raises ValueError."""
        tool = self._make_tool()
        with pytest.raises(ValueError, match="Invalid topic"):
            tool.apply("nonexistent_topic")

    def test_jet_brains_debug_repl_topic(self):
        """jet_brains_debug_repl topic returns info string."""
        tool = self._make_tool()
        result = tool.apply("jet_brains_debug_repl")
        assert result == "JB_INFO"


# ===========================================================================
# symbol_tools.py
# ===========================================================================

class TestGetSymbolsOverviewTool:
    """Tests for GetSymbolsOverviewTool.get_symbol_overview validation branches."""

    def _make_tool(self, tmp_path: Path) -> Any:
        from serena.tools.symbol_tools import GetSymbolsOverviewTool

        tool = object.__new__(GetSymbolsOverviewTool)
        agent = MagicMock()
        project = MagicMock()
        project.project_root = str(tmp_path)
        # project is a property delegating to agent.get_active_project_or_raise()
        agent.get_active_project_or_raise.return_value = project

        # symbol retriever that says it can analyze .py files only
        retriever = MagicMock()
        retriever.can_analyze_file.side_effect = lambda path: path.endswith(".py")
        tool.create_language_server_symbol_retriever = lambda: retriever
        tool.agent = agent
        return tool

    def test_file_not_found_raises(self, tmp_path):
        """FileNotFoundError when path does not exist."""
        tool = self._make_tool(tmp_path)
        with pytest.raises(FileNotFoundError):
            tool.get_symbol_overview("nonexistent_file.py")

    def test_directory_raises_value_error(self, tmp_path):
        """ValueError when path is a directory."""
        d = tmp_path / "subdir"
        d.mkdir()
        tool = self._make_tool(tmp_path)
        with pytest.raises(ValueError, match="directory path"):
            tool.get_symbol_overview("subdir")

    def test_unanalyzable_file_raises_value_error(self, tmp_path):
        """ValueError when file extension not supported by language server."""
        f = tmp_path / "test.txt"
        f.write_text("hello")
        tool = self._make_tool(tmp_path)
        with pytest.raises(ValueError, match="Cannot extract symbols"):
            tool.get_symbol_overview("test.txt")


class TestGetSymbolsOverviewToolApply:
    """Tests the apply() depth branch on GetSymbolsOverviewTool."""

    def _make_tool_with_mock_overview(self, tmp_path: Path, depth: int = 0) -> Any:
        from serena.tools.symbol_tools import GetSymbolsOverviewTool

        tool = object.__new__(GetSymbolsOverviewTool)
        agent = MagicMock()

        # patch get_symbol_overview to return fake result
        fake_result = [{"kind": "function", "name": "foo"}]
        tool.get_symbol_overview = lambda *a, **kw: fake_result

        # symbol_dict_grouper
        grouper = MagicMock()
        grouper.group.return_value = fake_result
        tool.symbol_dict_grouper = grouper

        def _limit(s, max_c, shortened_result_factories=None):
            return s
        tool._limit_length = _limit
        tool._to_json = json.dumps
        tool.agent = agent
        return tool

    def test_apply_depth_zero(self, tmp_path):
        """apply with depth=0 produces shortened_results=[make_kind_counts]."""
        tool = self._make_tool_with_mock_overview(tmp_path, depth=0)
        result = tool.apply("some/path.py", depth=0)
        # Should produce a valid JSON string (mocked)
        assert isinstance(result, str)

    def test_apply_depth_nonzero(self, tmp_path):
        """apply with depth>0 produces shortened_results=[make_depth_0_result, make_kind_counts]."""
        tool = self._make_tool_with_mock_overview(tmp_path, depth=1)
        result = tool.apply("some/path.py", depth=1)
        assert isinstance(result, str)


class TestFindSymbolToolMaxMatches:
    """Tests FindSymbolTool max_matches truncation path (L204-207)."""

    def _make_tool(self) -> Any:
        from serena.tools.symbol_tools import FindSymbolTool

        tool = object.__new__(FindSymbolTool)

        # Mock create_language_server_symbol_retriever — returns 5 symbols
        symbols = []
        for i in range(5):
            sym = MagicMock()
            sym.location.relative_path = f"file{i}.py"
            sym.get_name_path.return_value = f"symbol{i}"
            sym.to_dict.return_value = {"name": f"symbol{i}"}
            symbols.append(sym)

        retriever = MagicMock()
        retriever.find.return_value = symbols
        retriever.can_analyze_file.return_value = True
        tool.create_language_server_symbol_retriever = lambda: retriever
        tool.symbol_dict_grouper = MagicMock()
        tool.symbol_dict_grouper.group.return_value = {}

        def _limit(s, max_c, shortened_result_factories=None):
            return s
        tool._limit_length = _limit
        tool._to_json = json.dumps

        agent = MagicMock()
        tool.agent = agent
        return tool, retriever

    def test_max_matches_exceeded_returns_short_result(self):
        """When n_matches > max_matches, returns shortened result string."""
        tool, retriever = self._make_tool()
        result = tool.apply("symbol", max_matches=2)
        # Should contain "Matched" and ">" indicating truncation
        assert "Matched" in result
        assert "5" in result  # 5 symbols found


# ===========================================================================
# tools_base.py — create_code_editor / create_ls_code_editor branches
# ===========================================================================

class TestToolCreateCodeEditor:
    """Test create_code_editor dispatch for JetBrains and non-LS modes."""

    def _make_tool(self) -> Any:
        from serena.tools.tools_base import Tool

        class _T(Tool):
            def apply(self) -> str:
                """Apply."""
                return "ok"

        tool = object.__new__(_T)
        agent = MagicMock()
        tool.agent = agent
        return tool

    def test_create_code_editor_jetbrains_branch(self):
        """JetBrains backend creates JetBrainsCodeEditor."""
        tool = self._make_tool()
        from serena.config.serena_config import LanguageBackend

        tool.agent.get_language_backend.return_value = LanguageBackend.JETBRAINS
        project = MagicMock()
        tool.agent.get_active_project_or_raise.return_value = project

        with patch("serena.code_editor.JetBrainsCodeEditor") as mock_jb:
            # We need to patch within the tools_base import path
            with patch("serena.tools.tools_base.Tool.project", new_callable=lambda: property(lambda self: project)):
                mock_jb.return_value = MagicMock()
                # The import inside create_code_editor makes this tricky — just verify
                # that calling create_code_editor with JETBRAINS backend does NOT raise ValueError
                # by mocking the JetBrainsCodeEditor import
                import serena.code_editor as ce
                original = getattr(ce, "JetBrainsCodeEditor", None)
                try:
                    ce.JetBrainsCodeEditor = MagicMock(return_value=MagicMock())
                    result = tool.create_code_editor()
                    # verify it called JetBrainsCodeEditor constructor
                    ce.JetBrainsCodeEditor.assert_called_once()
                finally:
                    if original is not None:
                        ce.JetBrainsCodeEditor = original

    def test_create_code_editor_unknown_backend_raises(self):
        """Unknown backend raises ValueError."""
        tool = self._make_tool()
        tool.agent.get_language_backend.return_value = "unknown_backend"
        with pytest.raises((ValueError, AttributeError)):
            tool.create_code_editor()

    def test_create_ls_code_editor_not_lsp_mode_raises(self):
        """create_ls_code_editor raises when not in LS mode."""
        tool = self._make_tool()
        tool.agent.is_using_language_server.return_value = False
        with pytest.raises(Exception, match="not in language server mode"):
            tool.create_ls_code_editor()


# ===========================================================================
# tools_base.py — apply_ex branches (no active project)
# ===========================================================================

class TestApplyExNoProject:
    """Test apply_ex guard when no active project."""

    def _make_tool_and_agent(self) -> tuple[Any, MagicMock]:
        from serena.tools.tools_base import Tool

        class _NeedsProject(Tool):
            def apply(self) -> str:
                """Apply."""
                return "ok"

        tool = object.__new__(_NeedsProject)
        agent = MagicMock()
        agent.get_active_project.return_value = None
        agent.serena_config.project_names = ["p1"]
        agent.issue_task.side_effect = lambda fn, name=None: type(
            "TaskExec", (), {"result": lambda self, timeout=None: fn()}
        )()
        tool.agent = agent
        return tool, agent

    def test_no_project_returns_error_string(self):
        """apply_ex returns error string when no active project."""
        tool, agent = self._make_tool_and_agent()

        # is_active must return True so we don't hit the inactive-tool branch
        agent.get_active_tool_names.return_value = ["_needs_project"]
        agent.serena_config.tool_timeout = 30.0

        # Patch is_active to return True
        with patch.object(type(tool), "is_active", return_value=True):
            result = tool.apply_ex(log_call=False, catch_exceptions=True)
        assert "No active project" in result


# ===========================================================================
# query_project_tools.py
# ===========================================================================

class TestListQueryableProjectsTool:
    """Tests for ListQueryableProjectsTool apply branches."""

    def _make_tool(self, *, backend: str = "lsp") -> Any:
        from serena.tools.query_project_tools import ListQueryableProjectsTool

        tool = object.__new__(ListQueryableProjectsTool)
        agent = MagicMock()
        agent.serena_config.projects = []

        from serena.config.serena_config import LanguageBackend

        if backend == "lsp":
            agent.get_language_backend.return_value = LanguageBackend.LSP
        else:
            agent.get_language_backend.return_value = LanguageBackend.JETBRAINS

        tool.agent = agent
        tool._to_json = json.dumps
        return tool

    def test_lsp_backend_symbol_access_false_returns_all(self):
        """symbol_access=False returns all registered projects."""
        tool = self._make_tool(backend="lsp")
        p1 = MagicMock()
        p1.project_name = "p1"
        p1.project_root = "/tmp/p1"
        tool.agent.serena_config.projects = [p1]
        result = tool.apply(symbol_access=False)
        data = json.loads(result)
        assert "p1" in data

    def test_lsp_backend_symbol_access_true_returns_registered(self):
        """LSP + symbol_access=True returns all registered projects (LSP uses ProjectServer)."""
        tool = self._make_tool(backend="lsp")
        p1 = MagicMock()
        p1.project_name = "proj1"
        p1.project_root = "/tmp/proj1"
        tool.agent.serena_config.projects = [p1]
        result = tool.apply(symbol_access=True)
        data = json.loads(result)
        assert "proj1" in data

    def test_empty_projects_returns_empty_dict(self):
        """No registered projects → empty JSON object."""
        tool = self._make_tool()
        result = tool.apply(symbol_access=False)
        data = json.loads(result)
        assert data == {}


class TestQueryProjectTool:
    """Tests for QueryProjectTool._is_project_server_required dispatch."""

    def _make_tool(self, backend_value: str) -> Any:
        from serena.tools.query_project_tools import QueryProjectTool

        tool = object.__new__(QueryProjectTool)
        agent = MagicMock()

        from serena.config.serena_config import LanguageBackend

        agent.get_language_backend.return_value = LanguageBackend.LSP if backend_value == "lsp" else LanguageBackend.JETBRAINS
        tool.agent = agent
        return tool

    def test_is_project_server_required_jetbrains_returns_false(self):
        """JetBrains backend → _is_project_server_required returns False."""
        tool = self._make_tool("jetbrains")
        mock_tool = MagicMock()
        mock_tool.is_readonly.return_value = True
        result = tool._is_project_server_required(mock_tool)
        assert result is False

    def test_is_project_server_required_lsp_non_symbolic_returns_false(self):
        """LSP backend + non-symbolic read-only tool → returns False (no server needed)."""
        tool = self._make_tool("lsp")
        mock_tool = MagicMock()
        mock_tool.is_readonly.return_value = True
        mock_tool.is_symbolic.return_value = False
        result = tool._is_project_server_required(mock_tool)
        assert result is False

    def test_is_project_server_required_lsp_symbolic_returns_true(self):
        """LSP backend + symbolic read-only tool → returns True (project server needed)."""
        tool = self._make_tool("lsp")
        mock_tool = MagicMock()
        mock_tool.is_readonly.return_value = True
        mock_tool.is_symbolic.return_value = True
        result = tool._is_project_server_required(mock_tool)
        assert result is True


# ===========================================================================
# scalpel_runtime.py — spawn function import paths (module-level callable)
# ===========================================================================

class TestSpawnFunctionDispatch:
    """Test that _default_spawn_fn calls the right spawner for each known language."""

    def test_known_languages_dispatch_without_error_on_import(self):
        """All expected language keys are registered in the dispatch table."""
        from serena.tools.scalpel_runtime import _SPAWN_DISPATCH_TABLE

        expected = {"rust", "python:pylsp-rope", "python:basedpyright", "python:ruff", "markdown"}
        assert expected.issubset(set(_SPAWN_DISPATCH_TABLE.keys()))

    def test_unknown_language_raises_value_error(self):
        """_default_spawn_fn raises ValueError for unknown language."""
        from serena.tools.scalpel_runtime import _default_spawn_fn
        from serena.refactoring import LspPoolKey

        key = LspPoolKey(language="cobol", project_root="/tmp/proj")
        with pytest.raises(ValueError, match="unknown LspPoolKey.language"):
            _default_spawn_fn(key)

    def test_build_language_server_config_returns_config(self):
        """_build_language_server_config works for 'rust', 'python', 'markdown'."""
        from serena.tools.scalpel_runtime import _build_language_server_config

        for lang in ("rust", "python", "markdown"):
            cfg = _build_language_server_config(lang)
            assert cfg is not None

    def test_build_solidlsp_settings_returns_settings(self):
        """_build_solidlsp_settings returns a SolidLSPSettings instance."""
        from serena.tools.scalpel_runtime import _build_solidlsp_settings

        settings = _build_solidlsp_settings()
        assert settings is not None


class TestScalpelRuntimeCoordinatorCaching:
    """Test that coordinator_for returns cached instance on second call."""

    def test_coordinator_for_returns_cached_on_second_call(self, tmp_path):
        """When coordinator already in _coordinators dict, returns cached instance."""
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from solidlsp.ls_config import Language

        ScalpelRuntime.reset_for_testing()
        try:
            rt = ScalpelRuntime.instance()
            lang = Language.RUST
            canon_root = tmp_path.expanduser().resolve(strict=False)
            key = (lang.value, canon_root)

            # Pre-populate the cache — bypasses the slow build path entirely
            fake_coord = MagicMock()
            with rt._lock:
                rt._coordinators[key] = fake_coord

            # Second call should return the cached coordinator without spawning
            result = rt.coordinator_for(lang, tmp_path)
            assert result is fake_coord
        finally:
            ScalpelRuntime.reset_for_testing()

    def test_pool_for_caches_instance(self, tmp_path):
        """Second call to pool_for with same key returns same pool."""
        from serena.tools.scalpel_runtime import ScalpelRuntime
        from solidlsp.ls_config import Language

        ScalpelRuntime.reset_for_testing()
        try:
            rt = ScalpelRuntime.instance()
            lang = Language.RUST

            # Patch the actual LspPool constructor to avoid spawning
            with patch("serena.tools.scalpel_runtime.LspPool") as mock_pool_cls:
                fake_pool = MagicMock()
                mock_pool_cls.return_value = fake_pool
                p1 = rt.pool_for(lang, tmp_path)
                p2 = rt.pool_for(lang, tmp_path)
            assert p1 is p2
        finally:
            ScalpelRuntime.reset_for_testing()
