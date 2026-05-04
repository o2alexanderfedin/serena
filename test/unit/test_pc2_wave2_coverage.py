"""PC2 Wave-2 coverage uplift — targeted tests for remaining uncovered ranges.

Targets:
- multi_server.py L448-449 (_apply_priority: all disabled from active set check)
- multi_server.py L464 (_dedup: already-assigned cluster member skipped)
- multi_server.py L598, L602 (_apply_text_edits_in_memory: out-of-bounds lines)
- multi_server.py L632, L634-635 (_check_workspace_boundary: create/delete/rename kinds)
- multi_server.py L647-654 (_check_workspace_boundary: legacy changes map)
- multi_server.py L713-716 (_reconcile_rename_edits: whole-file → line hunks)
- multi_server.py L938-981 (supports_kind Tier 3 branches)
- multi_server.py L1167-1253 (merge_code_actions data.id + disabled surfacing)
- multi_server.py L1293-1426 (merge_and_validate_code_actions)
- python_strategy.py L82-136 (PythonStrategy.build_servers + coordinator)
- python_strategy.py L227-229 (_PythonInterpreter.discover step exception → attempt logged)
- python_strategy.py L493-533 (_rope_changes_to_workspace_edit with fake changes)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring._async_check import AWAITED_SERVER_METHODS
from serena.refactoring.multi_server import (
    MultiServerCoordinator,
    _apply_text_edits_in_memory,
    _check_workspace_boundary,
    _reconcile_rename_edits,
    _walk_document_symbols,
)
from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_server(server_id: str, caps: dict[str, Any] | None = None) -> MagicMock:
    server = MagicMock()
    for method_name in AWAITED_SERVER_METHODS:
        getattr(server, method_name)._o2_async_callable = True
    server.server_id = server_id
    server.server_capabilities = MagicMock(return_value=caps or {})
    return server


def _make_coord(servers: dict[str, MagicMock]) -> MultiServerCoordinator:
    return MultiServerCoordinator(
        servers=servers,
        dynamic_registry=DynamicCapabilityRegistry(),
        catalog=None,
    )


# ---------------------------------------------------------------------------
# _apply_text_edits_in_memory edge cases
# ---------------------------------------------------------------------------


class TestApplyTextEditsInMemory:
    def test_out_of_bounds_start_line_clamps(self) -> None:
        src = "hello\n"
        edits = [{
            "range": {
                "start": {"line": 999, "character": 0},
                "end": {"line": 999, "character": 0},
            },
            "newText": "world\n",
        }]
        result = _apply_text_edits_in_memory(src, edits)
        # Out-of-bounds appended at end.
        assert "world" in result

    def test_out_of_bounds_end_line_clamps(self) -> None:
        src = "line1\nline2\n"
        edits = [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 999, "character": 0},
            },
            "newText": "replaced\n",
        }]
        result = _apply_text_edits_in_memory(src, edits)
        assert "replaced" in result

    def test_normal_edit(self) -> None:
        src = "hello world\n"
        edits = [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 5},
            },
            "newText": "goodbye",
        }]
        result = _apply_text_edits_in_memory(src, edits)
        assert "goodbye" in result


# ---------------------------------------------------------------------------
# _check_workspace_boundary with create/delete/rename kinds
# ---------------------------------------------------------------------------


class TestCheckWorkspaceBoundaryKinds:
    def test_create_kind_in_workspace(self, tmp_path: Path) -> None:
        f = tmp_path / "new.py"
        edit = {
            "documentChanges": [{"kind": "create", "uri": f.as_uri()}],
        }
        ok, reason = _check_workspace_boundary(edit, [str(tmp_path)])
        assert ok is True

    def test_delete_kind_outside_workspace(self, tmp_path: Path) -> None:
        import tempfile
        other = Path(tempfile.mkdtemp()) / "old.py"
        edit = {
            "documentChanges": [{"kind": "delete", "uri": other.as_uri()}],
        }
        ok, reason = _check_workspace_boundary(edit, [str(tmp_path)])
        assert ok is False
        assert "OUT_OF_WORKSPACE" in (reason or "")

    def test_rename_kind_old_uri_outside_workspace(self, tmp_path: Path) -> None:
        import tempfile
        old = Path(tempfile.mkdtemp()) / "old.py"
        new = tmp_path / "new.py"
        edit = {
            "documentChanges": [{
                "kind": "rename",
                "oldUri": old.as_uri(),
                "newUri": new.as_uri(),
            }],
        }
        ok, reason = _check_workspace_boundary(edit, [str(tmp_path)])
        assert ok is False

    def test_rename_kind_new_uri_outside_workspace(self, tmp_path: Path) -> None:
        import tempfile
        old = tmp_path / "old.py"
        new = Path(tempfile.mkdtemp()) / "new.py"
        edit = {
            "documentChanges": [{
                "kind": "rename",
                "oldUri": old.as_uri(),
                "newUri": new.as_uri(),
            }],
        }
        ok, reason = _check_workspace_boundary(edit, [str(tmp_path)])
        assert ok is False

    def test_legacy_changes_map_outside_workspace(self, tmp_path: Path) -> None:
        import tempfile
        other = Path(tempfile.mkdtemp()) / "x.py"
        edit = {
            "changes": {
                other.as_uri(): [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "newText": ""},
                ],
            },
        }
        ok, reason = _check_workspace_boundary(edit, [str(tmp_path)])
        assert ok is False
        assert "OUT_OF_WORKSPACE" in (reason or "")

    def test_legacy_changes_map_in_workspace(self, tmp_path: Path) -> None:
        f = tmp_path / "x.py"
        f.write_text("x = 1\n")
        edit = {
            "changes": {
                f.as_uri(): [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "newText": ""},
                ],
            },
        }
        ok, reason = _check_workspace_boundary(edit, [str(tmp_path)])
        assert ok is True


# ---------------------------------------------------------------------------
# _reconcile_rename_edits: whole-file edit converted to line hunks
# ---------------------------------------------------------------------------


class TestReconcileRenameEditsWholeFile:
    def test_whole_file_edit_converted_to_line_hunks(self, tmp_path: Path) -> None:
        """Multi-line span triggers line-hunk decomposition via difflib."""
        f = tmp_path / "foo.py"
        original = "def old_name():\n    return 1\n"
        f.write_text(original)
        new_text = "def new_name():\n    return 1\n"
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri()},
                "edits": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 10, "character": 0},  # spans multiple lines
                    },
                    "newText": new_text,
                }],
            }],
        }
        result = _reconcile_rename_edits(edit, source_reader=lambda uri: original)
        # Should get at least one hunk back.
        assert len(result) >= 1
        # The hunk covering line 0 should rename old_name to new_name.
        texts = [te["newText"] for _, te in result]
        assert any("new_name" in t for t in texts)


# ---------------------------------------------------------------------------
# _walk_document_symbols
# ---------------------------------------------------------------------------


class TestWalkDocumentSymbols:
    def test_top_level_match(self) -> None:
        nodes = [
            {"name": "foo", "selectionRange": {"start": {"line": 0, "character": 4}}, "children": []},
        ]
        result = _walk_document_symbols(nodes, ["foo"])
        assert result == {"line": 0, "character": 4}

    def test_no_match_returns_none(self) -> None:
        nodes = [{"name": "bar", "selectionRange": {"start": {"line": 0, "character": 0}}, "children": []}]
        result = _walk_document_symbols(nodes, ["missing"])
        assert result is None

    def test_empty_segments_returns_none(self) -> None:
        result = _walk_document_symbols([], [])
        assert result is None

    def test_non_dict_nodes_skipped(self) -> None:
        nodes = ["not-a-dict", {"name": "foo", "selectionRange": {"start": {"line": 5, "character": 2}}, "children": []}]
        result = _walk_document_symbols(nodes, ["foo"])
        assert result == {"line": 5, "character": 2}

    def test_nested_match(self) -> None:
        inner = {"name": "method", "selectionRange": {"start": {"line": 3, "character": 8}}, "children": []}
        outer = {"name": "MyClass", "children": [inner]}
        result = _walk_document_symbols([outer], ["MyClass", "method"])
        assert result == {"line": 3, "character": 8}

    def test_match_fallback_to_range(self) -> None:
        node = {
            "name": "foo",
            "range": {"start": {"line": 2, "character": 0}},
            "children": [],
        }
        result = _walk_document_symbols([node], ["foo"])
        assert result == {"line": 2, "character": 0}

    def test_match_incomplete_range_returns_none(self) -> None:
        node = {
            "name": "foo",
            "selectionRange": {"start": {"line": 2}},  # missing 'character'
            "children": [],
        }
        result = _walk_document_symbols([node], ["foo"])
        assert result is None


# ---------------------------------------------------------------------------
# supports_kind — Tier 3 branches
# ---------------------------------------------------------------------------


class TestSupportsKind:
    def _make_catalog_record(self, language: str, kind: str, server_id: str) -> Any:
        from serena.refactoring.capabilities import CapabilityRecord, CapabilityCatalog
        record = CapabilityRecord(
            id=f"{language}-{kind}-{server_id}",
            language=language,
            kind=kind,
            source_server=server_id,  # type: ignore[arg-type]
        )
        catalog = CapabilityCatalog(records=[record])
        return catalog

    def test_no_catalog_returns_false(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        # catalog=None → Tier 1 lookup fails → False.
        assert coord.supports_kind("python", "refactor.extract") is False

    def test_catalog_match_but_code_action_unavailable(self) -> None:
        catalog = self._make_catalog_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server("pylsp-rope")
        server.server_capabilities.return_value = {}  # no codeActionProvider
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=DynamicCapabilityRegistry(),
            catalog=catalog,
        )
        assert coord.supports_kind("python", "refactor.extract") is False

    def test_catalog_match_dynamic_only_no_static_filter(self) -> None:
        """Dynamic registration without static kind filter → any kind accepted."""
        catalog = self._make_catalog_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server("pylsp-rope")
        server.server_capabilities.return_value = {}  # no static codeActionProvider
        registry = DynamicCapabilityRegistry()
        registry.register("pylsp-rope", "reg-1", "textDocument/codeAction", {})
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=registry,
            catalog=catalog,
        )
        assert coord.supports_kind("python", "refactor.extract") is True

    def test_catalog_match_static_caps_code_action_true(self) -> None:
        """Static codeActionProvider=true → any kind accepted."""
        catalog = self._make_catalog_record("python", "refactor.extract", "pylsp-rope")
        server = _make_async_server("pylsp-rope")
        server.server_capabilities.return_value = {"codeActionProvider": True}
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=DynamicCapabilityRegistry(),
            catalog=catalog,
        )
        assert coord.supports_kind("python", "refactor.extract") is True

    def test_catalog_match_static_caps_empty_kinds_list(self) -> None:
        """codeActionKinds=[] → any kind accepted per LSP 3.17."""
        catalog = self._make_catalog_record("python", "quickfix", "pylsp-rope")
        server = _make_async_server("pylsp-rope")
        server.server_capabilities.return_value = {
            "codeActionProvider": {"codeActionKinds": []},
        }
        coord = MultiServerCoordinator(
            servers={"pylsp-rope": server},
            dynamic_registry=DynamicCapabilityRegistry(),
            catalog=catalog,
        )
        assert coord.supports_kind("python", "quickfix") is True

    def test_catalog_match_static_caps_kinds_list_includes_kind(self) -> None:
        catalog = self._make_catalog_record("rust", "refactor.extract", "rust-analyzer")
        server = _make_async_server("rust-analyzer")
        server.server_capabilities.return_value = {
            "codeActionProvider": {"codeActionKinds": ["refactor", "refactor.extract"]},
        }
        coord = MultiServerCoordinator(
            servers={"rust-analyzer": server},
            dynamic_registry=DynamicCapabilityRegistry(),
            catalog=catalog,
        )
        assert coord.supports_kind("rust", "refactor.extract") is True

    def test_catalog_match_static_caps_kinds_list_excludes_kind(self) -> None:
        catalog = self._make_catalog_record("rust", "source.organizeImports", "rust-analyzer")
        server = _make_async_server("rust-analyzer")
        server.server_capabilities.return_value = {
            "codeActionProvider": {"codeActionKinds": ["refactor.extract"]},
        }
        coord = MultiServerCoordinator(
            servers={"rust-analyzer": server},
            dynamic_registry=DynamicCapabilityRegistry(),
            catalog=catalog,
        )
        assert coord.supports_kind("rust", "source.organizeImports") is False

    def test_catalog_match_prefix_child_kind(self) -> None:
        """Catalog records refactor.extract; query for refactor.extract.module matches."""
        catalog = self._make_catalog_record("rust", "refactor.extract", "rust-analyzer")
        server = _make_async_server("rust-analyzer")
        server.server_capabilities.return_value = {
            "codeActionProvider": {"codeActionKinds": ["refactor.extract"]},
        }
        coord = MultiServerCoordinator(
            servers={"rust-analyzer": server},
            dynamic_registry=DynamicCapabilityRegistry(),
            catalog=catalog,
        )
        # LSP §3.18.1: refactor.extract matches refactor.extract.module
        assert coord.supports_kind("rust", "refactor.extract.module") is True


# ---------------------------------------------------------------------------
# merge_code_actions edge cases (data.id, disabled in disabled_pairs)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMergeCodeActionsEdgeCases:
    async def test_action_with_data_id_uses_it(self) -> None:
        server = _make_async_server("ruff")
        action_edit = {"documentChanges": []}

        async def _actions(**kwargs: Any) -> list:
            return [{
                "title": "fix",
                "kind": "source.fixAll",
                "edit": action_edit,
                "data": {"id": "my-special-id"},
            }]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"ruff": server})
        merged = await coord.merge_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
        )
        assert len(merged) >= 1
        assert merged[0].id == "my-special-id"
        assert coord.get_action_edit("my-special-id") == action_edit

    async def test_disabled_action_in_disabled_pairs_surfaced(self) -> None:
        """Disabled actions are surfaced with their disabled_reason populated."""
        server = _make_async_server("basedpyright")

        async def _actions(**kwargs: Any) -> list:
            return [
                {
                    "title": "normal fix",
                    "kind": "quickfix",
                },
                {
                    "title": "disabled fix",
                    "kind": "quickfix",
                    "disabled": {"reason": "feature not available"},
                    "data": {"id": "disabled-1"},
                },
            ]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"basedpyright": server})
        merged = await coord.merge_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
        )
        disabled = [m for m in merged if m.disabled_reason]
        assert len(disabled) >= 1
        assert disabled[0].disabled_reason == "feature not available"


# ---------------------------------------------------------------------------
# merge_and_validate_code_actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMergeAndValidateCodeActions:
    async def test_empty_results_when_no_servers_respond(self) -> None:
        server = _make_async_server("pylsp-rope")

        async def _empty(**kwargs: Any) -> list:
            return []

        server.request_code_actions.side_effect = _empty
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        auto, surfaced = await coord.merge_and_validate_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
        )
        assert auto == []
        assert surfaced == []

    async def test_action_no_edit_goes_to_surfaced_as_no_edit(self, tmp_path: Path) -> None:
        """An action without an 'edit' key fails invariant → surfaced with NO_EDIT."""
        server = _make_async_server("pylsp-rope")

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "no-edit action", "kind": "quickfix"}]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        auto, surfaced = await coord.merge_and_validate_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
            workspace_folders=[str(tmp_path)],
        )
        assert len(auto) == 0
        assert len(surfaced) >= 1
        assert "NO_EDIT" in (surfaced[0].disabled_reason or "")

    async def test_action_with_valid_edit_goes_to_auto_apply(self, tmp_path: Path) -> None:
        """An action with a valid in-workspace edit goes to auto_apply."""
        f = tmp_path / "x.py"
        f.write_text("x = 1\n")
        server = _make_async_server("pylsp-rope")
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri(), "version": None},
                "edits": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "y = 2",
                }],
            }],
        }

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "fix", "kind": "source.fixAll", "edit": edit}]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        auto, surfaced = await coord.merge_and_validate_code_actions(
            file=str(f),
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
            workspace_folders=[str(tmp_path)],
        )
        # The edit should pass all invariants and be in auto_apply.
        assert len(auto) == 1
        assert auto[0].title == "fix"

    async def test_disabled_action_always_surfaced(self, tmp_path: Path) -> None:
        server = _make_async_server("basedpyright")

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "disabled", "kind": "quickfix", "disabled": {"reason": "unavailable"}}]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"basedpyright": server})
        auto, surfaced = await coord.merge_and_validate_code_actions(
            file="/tmp/x.py",
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
            workspace_folders=[str(tmp_path)],
        )
        assert len(auto) == 0
        assert len(surfaced) == 1
        assert surfaced[0].disabled_reason == "unavailable"

    async def test_stale_version_goes_to_surfaced(self, tmp_path: Path) -> None:
        f = tmp_path / "stale.py"
        f.write_text("x = 1\n")
        server = _make_async_server("pylsp-rope")
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri(), "version": 1},  # stale
                "edits": [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}, "newText": "y"}],
            }],
        }

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "stale fix", "kind": "source.fixAll", "edit": edit}]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        auto, surfaced = await coord.merge_and_validate_code_actions(
            file=str(f),
            start={"line": 0, "character": 0},
            end={"line": 0, "character": 0},
            workspace_folders=[str(tmp_path)],
            document_versions={f.as_uri(): 5},  # server has version 5
        )
        assert len(auto) == 0
        assert len(surfaced) == 1
        assert "STALE_VERSION" in (surfaced[0].disabled_reason or "")

    async def test_env_extra_paths_applied(self, tmp_path: Path) -> None:
        """O2_SCALPEL_WORKSPACE_EXTRA_PATHS env var is honoured."""
        f = tmp_path / "extra.py"
        f.write_text("x = 1\n")
        server = _make_async_server("pylsp-rope")
        edit = {
            "documentChanges": [{
                "textDocument": {"uri": f.as_uri(), "version": None},
                "edits": [],
            }],
        }

        async def _actions(**kwargs: Any) -> list:
            return [{"title": "fix", "kind": "source.fixAll", "edit": edit}]

        server.request_code_actions.side_effect = _actions
        server.request_code_actions._o2_async_callable = True

        coord = _make_coord({"pylsp-rope": server})
        with patch.dict(os.environ, {"O2_SCALPEL_WORKSPACE_EXTRA_PATHS": str(tmp_path)}):
            auto, surfaced = await coord.merge_and_validate_code_actions(
                file=str(f),
                start={"line": 0, "character": 0},
                end={"line": 0, "character": 0},
                workspace_folders=[],  # no workspace folders
            )
        # Extra path covers the file → should auto-apply.
        assert len(auto) == 1


# ---------------------------------------------------------------------------
# PythonStrategy.build_servers + coordinator (with mock pool)
# ---------------------------------------------------------------------------


class TestPythonStrategyBuildServers:
    def test_build_servers_returns_three_servers(self) -> None:
        from serena.refactoring.python_strategy import PythonStrategy
        from serena.refactoring.lsp_pool import LspPool, LspPoolKey

        # Build a mock pool that returns fake servers.
        fake_servers: dict[str, MagicMock] = {}
        for name in ["pylsp-rope", "basedpyright", "ruff"]:
            srv = _make_async_server(name)
            fake_servers[name] = srv

        call_counter: list[str] = []

        def _spawn(key: LspPoolKey) -> MagicMock:
            # Map pool language tag back to server name.
            for sid in ["pylsp-rope", "basedpyright", "ruff"]:
                if sid in key.language:
                    call_counter.append(sid)
                    return fake_servers[sid]
            return _make_async_server("unknown")

        pool = LspPool(
            spawn_fn=_spawn,
            idle_shutdown_seconds=600.0,
            ram_ceiling_mb=4096.0,
            reaper_enabled=False,
        )
        strategy = PythonStrategy(pool=pool)
        servers = strategy.build_servers(Path("/tmp/test_project"))
        # Should have exactly 3 entries.
        assert set(servers.keys()) == {"pylsp-rope", "basedpyright", "ruff"}
        pool.shutdown_all()

    def test_coordinator_with_configure_interpreter_false(self) -> None:
        from serena.refactoring.python_strategy import PythonStrategy
        from serena.refactoring.lsp_pool import LspPool, LspPoolKey

        fake_servers: dict[str, MagicMock] = {}
        for name in ["pylsp-rope", "basedpyright", "ruff"]:
            fake_servers[name] = _make_async_server(name)

        def _spawn(key: LspPoolKey) -> MagicMock:
            for sid in ["pylsp-rope", "basedpyright", "ruff"]:
                if sid in key.language:
                    return fake_servers[sid]
            return _make_async_server("unknown")

        pool = LspPool(
            spawn_fn=_spawn,
            idle_shutdown_seconds=600.0,
            ram_ceiling_mb=4096.0,
            reaper_enabled=False,
        )
        strategy = PythonStrategy(pool=pool)
        coord = strategy.coordinator(Path("/tmp/test_project2"), configure_interpreter=False)
        assert isinstance(coord, MultiServerCoordinator)
        pool.shutdown_all()

    def test_coordinator_interpreter_not_found_continues(self) -> None:
        """When interpreter discovery fails, coordinator is still built."""
        from serena.refactoring.python_strategy import PythonStrategy, PythonInterpreterNotFound
        from serena.refactoring.lsp_pool import LspPool, LspPoolKey

        fake_servers: dict[str, MagicMock] = {}
        for name in ["pylsp-rope", "basedpyright", "ruff"]:
            fake_servers[name] = _make_async_server(name)

        def _spawn(key: LspPoolKey) -> MagicMock:
            for sid in ["pylsp-rope", "basedpyright", "ruff"]:
                if sid in key.language:
                    return fake_servers[sid]
            return _make_async_server("unknown")

        pool = LspPool(
            spawn_fn=_spawn,
            idle_shutdown_seconds=600.0,
            ram_ceiling_mb=4096.0,
            reaper_enabled=False,
        )
        strategy = PythonStrategy(pool=pool)
        with patch("serena.refactoring.python_strategy._PythonInterpreter.discover") as mock_discover:
            mock_discover.side_effect = PythonInterpreterNotFound([])
            coord = strategy.coordinator(Path("/tmp/test_project3"), configure_interpreter=True)
        assert isinstance(coord, MultiServerCoordinator)
        pool.shutdown_all()

    def test_coordinator_configure_python_path_called(self) -> None:
        """When discovery succeeds, configure_python_path is called on basedpyright."""
        from serena.refactoring.python_strategy import (
            PythonStrategy, _ResolvedInterpreter, _PythonInterpreter
        )
        from serena.refactoring.lsp_pool import LspPool, LspPoolKey

        bp_server = _make_async_server("basedpyright")
        bp_server.configure_python_path = MagicMock()

        fake_servers: dict[str, MagicMock] = {
            "pylsp-rope": _make_async_server("pylsp-rope"),
            "basedpyright": bp_server,
            "ruff": _make_async_server("ruff"),
        }

        def _spawn(key: LspPoolKey) -> MagicMock:
            for sid in ["pylsp-rope", "basedpyright", "ruff"]:
                if sid in key.language:
                    return fake_servers[sid]
            return _make_async_server("unknown")

        pool = LspPool(
            spawn_fn=_spawn,
            idle_shutdown_seconds=600.0,
            ram_ceiling_mb=4096.0,
            reaper_enabled=False,
        )
        strategy = PythonStrategy(pool=pool)
        resolved = _ResolvedInterpreter(
            path=Path("/usr/bin/python3"),
            version=(3, 11),
            discovery_step=14,
        )
        with patch.object(_PythonInterpreter, "discover", return_value=resolved):
            strategy.coordinator(Path("/tmp/test_project4"), configure_interpreter=True)
        bp_server.configure_python_path.assert_called_once_with("/usr/bin/python3")
        pool.shutdown_all()


# ---------------------------------------------------------------------------
# _rope_changes_to_workspace_edit
# ---------------------------------------------------------------------------


class TestRopeChangesToWorkspaceEdit:
    def test_change_contents_converted(self, tmp_path: Path) -> None:
        """ChangeContents → TextDocumentEdit with full-file replace."""
        from serena.refactoring.python_strategy import _rope_changes_to_workspace_edit

        # Build minimal fake rope objects without importing rope.
        fake_project = MagicMock()
        fake_project.address = str(tmp_path)

        fake_resource = MagicMock()
        fake_resource.path = "module.py"

        # Create fake ChangeContents
        try:
            from rope.base.change import ChangeContents
            change = MagicMock(spec=ChangeContents)
            change.resource = fake_resource
            change.new_contents = "new content\n"
        except ImportError:
            pytest.skip("rope not available")
            return

        fake_changes = MagicMock()
        fake_changes.changes = [change]

        result = _rope_changes_to_workspace_edit(fake_project, fake_changes)
        assert len(result["documentChanges"]) == 1
        dc = result["documentChanges"][0]
        assert "textDocument" in dc
        assert dc["edits"][0]["newText"] == "new content\n"

    def test_move_resource_converted_to_rename(self, tmp_path: Path) -> None:
        from serena.refactoring.python_strategy import _rope_changes_to_workspace_edit

        fake_project = MagicMock()
        fake_project.address = str(tmp_path)

        try:
            from rope.base.change import MoveResource
            change = MagicMock(spec=MoveResource)
            change.resource = MagicMock()
            change.resource.path = "old.py"
            change.new_resource = MagicMock()
            change.new_resource.path = "new.py"
        except ImportError:
            pytest.skip("rope not available")
            return

        fake_changes = MagicMock()
        fake_changes.changes = [change]

        result = _rope_changes_to_workspace_edit(fake_project, fake_changes)
        assert len(result["documentChanges"]) == 1
        dc = result["documentChanges"][0]
        assert dc["kind"] == "rename"
        assert "old.py" in dc["oldUri"]
        assert "new.py" in dc["newUri"]

    def test_create_resource_converted(self, tmp_path: Path) -> None:
        from serena.refactoring.python_strategy import _rope_changes_to_workspace_edit

        fake_project = MagicMock()
        fake_project.address = str(tmp_path)

        try:
            from rope.base.change import CreateResource
            change = MagicMock(spec=CreateResource)
            change.resource = MagicMock()
            change.resource.path = "new_module.py"
        except ImportError:
            pytest.skip("rope not available")
            return

        fake_changes = MagicMock()
        fake_changes.changes = [change]

        result = _rope_changes_to_workspace_edit(fake_project, fake_changes)
        assert result["documentChanges"][0]["kind"] == "create"

    def test_remove_resource_converted(self, tmp_path: Path) -> None:
        from serena.refactoring.python_strategy import _rope_changes_to_workspace_edit

        fake_project = MagicMock()
        fake_project.address = str(tmp_path)

        try:
            from rope.base.change import RemoveResource
            change = MagicMock(spec=RemoveResource)
            change.resource = MagicMock()
            change.resource.path = "deleted.py"
        except ImportError:
            pytest.skip("rope not available")
            return

        fake_changes = MagicMock()
        fake_changes.changes = [change]

        result = _rope_changes_to_workspace_edit(fake_project, fake_changes)
        assert result["documentChanges"][0]["kind"] == "delete"
