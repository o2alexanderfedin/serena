"""PC2 Wave-3 coverage uplift — targeted tests for remaining uncovered ranges.

Targets (post-wave-2 gap list):
- multi_server.py L448-449 (_dedup._rank: ValueError branch — server not in priority)
- multi_server.py L464     (_dedup: j already assigned to another cluster winner)
- multi_server.py L1519-1556 (find_symbol_position: doc-symbol walk + ws-symbol fallback)
- multi_server.py L1579-1629 (find_symbol_range: doc-symbol walk + ws-symbol fallback)
- multi_server.py L1662-1695 (request_references: name_path branch + refs returned)
- multi_server.py L1792-1793 (find_symbol_range: no-end ws-symbol path)
- rust_strategy.py  L67-68, L89, L98-100, L115-117 (build_servers + execute_command_whitelist)
- prolog_strategy.py  L91, L98-100, L112 (build_servers + execute_command_whitelist)
- problog_strategy.py L93, L102-104, L113 (build_servers + execute_command_whitelist)
- smt2_strategy.py   L79, L86-88, L97   (build_servers + execute_command_whitelist)
- python_strategy.py L130-131            (_PythonInterpreterNotFound warning path)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from serena.refactoring._async_check import AWAITED_SERVER_METHODS
from serena.refactoring.multi_server import (
    MultiServerCoordinator,
    _dedup,
    _walk_document_symbols,
    _walk_document_symbols_for_range,
)
from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


def _make_async_server(server_id: str, caps: dict[str, Any] | None = None) -> MagicMock:
    server = MagicMock()
    for method_name in AWAITED_SERVER_METHODS:
        getattr(server, method_name)._o2_async_callable = True
    server.server_id = server_id
    server.server_capabilities = MagicMock(return_value=caps or {})
    return server


def _make_coord(servers: dict[str, MagicMock], catalog: Any = None) -> MultiServerCoordinator:
    return MultiServerCoordinator(
        servers=servers,
        dynamic_registry=DynamicCapabilityRegistry(),
        catalog=catalog,
    )


# ---------------------------------------------------------------------------
# _dedup — ValueError branch + already-assigned cluster member
# ---------------------------------------------------------------------------


class TestDedupEdgeCases:
    def test_unknown_server_id_sorts_last(self) -> None:
        """_rank raises ValueError for server not in priority — maps to len(priority)."""
        from serena.refactoring.multi_server import _dedup

        # priority has only "pylsp-rope"; "basedpyright" is unknown → sorts last.
        candidates = [
            ("basedpyright", {"title": "Fix it"}),
            ("pylsp-rope", {"title": "Fix it"}),
        ]
        result = _dedup(candidates, priority=("pylsp-rope",))
        # pylsp-rope wins (lower rank); basedpyright is a duplicate.
        assert len(result) == 1
        winner_sid = result[0][0]
        assert winner_sid == "pylsp-rope"
        dropped = result[0][2]
        assert len(dropped) == 1
        assert dropped[0][0] == "basedpyright"

    def test_already_assigned_cluster_member_skipped(self) -> None:
        """With 3 candidates, j=2 already assigned to winner 0 → L464 continue fires."""
        from serena.refactoring.multi_server import _dedup

        # candidates 0 and 2 share the same title → they cluster together
        # when i=0 processes j=2. When i=1 later processes j=2, the
        # cluster_winner_idx_per_member[j] != -1 guard fires.
        title_shared = "Import numpy"
        candidates = [
            ("pylsp-rope", {"title": title_shared}),   # rank 0
            ("ruff",       {"title": "Other action"}),  # rank 1
            ("basedpyright", {"title": title_shared}),  # rank 2 — clusters with 0
        ]
        priority = ("pylsp-rope", "ruff", "basedpyright")
        result = _dedup(candidates, priority=priority)
        # We should get 2 winners: one for "Import numpy" (pylsp-rope) and
        # one for "Other action" (ruff). basedpyright was already absorbed.
        assert len(result) == 2
        winner_ids = {r[0] for r in result}
        assert "pylsp-rope" in winner_ids
        assert "ruff" in winner_ids
        assert "basedpyright" not in winner_ids

    def test_unknown_server_not_in_priority_is_valid_winner(self) -> None:
        """An unknown server with unique title wins its own cluster."""
        from serena.refactoring.multi_server import _dedup

        candidates = [
            ("unknown-server", {"title": "Unique action"}),
        ]
        result = _dedup(candidates, priority=("pylsp-rope",))
        assert len(result) == 1
        assert result[0][0] == "unknown-server"


# ---------------------------------------------------------------------------
# Strategy build_servers + execute_command_whitelist
# ---------------------------------------------------------------------------


class TestRustStrategyMethods:
    def test_build_servers_acquires_from_pool(self) -> None:
        from serena.refactoring.rust_strategy import RustStrategy

        mock_server = MagicMock()
        pool = MagicMock()
        pool.acquire.return_value = mock_server

        strategy = RustStrategy(pool=pool)
        servers = strategy.build_servers(Path("/tmp/project"))

        assert "rust-analyzer" in servers
        assert servers["rust-analyzer"] is mock_server
        assert pool.acquire.call_count == 1

    def test_execute_command_whitelist_default(self) -> None:
        from serena.refactoring.rust_strategy import (
            RustStrategy,
            _DEFAULT_RUST_EXECUTE_COMMAND_WHITELIST,
        )
        result = RustStrategy.execute_command_whitelist()
        assert result == _DEFAULT_RUST_EXECUTE_COMMAND_WHITELIST

    def test_execute_command_whitelist_with_clippy_flag(self) -> None:
        from serena.refactoring.rust_strategy import (
            RustStrategy,
            _DEFAULT_RUST_EXECUTE_COMMAND_WHITELIST,
            _CLIPPY_MULTI_SERVER_VERBS,
            _CLIPPY_MULTI_SERVER_FEATURE_FLAG,
        )
        with patch.dict(os.environ, {_CLIPPY_MULTI_SERVER_FEATURE_FLAG: "1"}):
            result = RustStrategy.execute_command_whitelist()
        assert result == _DEFAULT_RUST_EXECUTE_COMMAND_WHITELIST | _CLIPPY_MULTI_SERVER_VERBS

    def test_feature_flag_truthy_values(self) -> None:
        from serena.refactoring.rust_strategy import _feature_flag_enabled

        for val in ("1", "true", "True", "yes", "on", "ON", "YES"):
            with patch.dict(os.environ, {"MY_FLAG": val}):
                assert _feature_flag_enabled("MY_FLAG") is True
        for val in ("0", "false", "no", "", "off"):
            with patch.dict(os.environ, {"MY_FLAG": val}):
                assert _feature_flag_enabled("MY_FLAG") is False


class TestPrologStrategyMethods:
    def test_build_servers_acquires_from_pool(self) -> None:
        from serena.refactoring.prolog_strategy import PrologStrategy

        mock_server = MagicMock()
        pool = MagicMock()
        pool.acquire.return_value = mock_server

        strategy = PrologStrategy(pool=pool)
        servers = strategy.build_servers(Path("/tmp/prolog_project"))

        assert "swipl-lsp" in servers
        assert servers["swipl-lsp"] is mock_server

    def test_execute_command_whitelist_is_empty(self) -> None:
        from serena.refactoring.prolog_strategy import PrologStrategy

        result = PrologStrategy.execute_command_whitelist()
        assert result == frozenset()


class TestProblogStrategyMethods:
    def test_build_servers_acquires_from_pool(self) -> None:
        from serena.refactoring.problog_strategy import ProblogStrategy

        mock_server = MagicMock()
        pool = MagicMock()
        pool.acquire.return_value = mock_server

        strategy = ProblogStrategy(pool=pool)
        servers = strategy.build_servers(Path("/tmp/problog_project"))

        assert "problog-lsp" in servers
        assert servers["problog-lsp"] is mock_server

    def test_execute_command_whitelist_is_empty(self) -> None:
        from serena.refactoring.problog_strategy import ProblogStrategy

        result = ProblogStrategy.execute_command_whitelist()
        assert result == frozenset()


class TestSmt2StrategyMethods:
    def test_build_servers_acquires_from_pool(self) -> None:
        from serena.refactoring.smt2_strategy import Smt2Strategy

        mock_server = MagicMock()
        pool = MagicMock()
        pool.acquire.return_value = mock_server

        strategy = Smt2Strategy(pool=pool)
        servers = strategy.build_servers(Path("/tmp/smt2_project"))

        assert "dolmenls" in servers
        assert servers["dolmenls"] is mock_server

    def test_execute_command_whitelist_is_empty(self) -> None:
        from serena.refactoring.smt2_strategy import Smt2Strategy

        result = Smt2Strategy.execute_command_whitelist()
        assert result == frozenset()


# ---------------------------------------------------------------------------
# python_strategy.py — PythonInterpreterNotFound warning path (L130-131)
# ---------------------------------------------------------------------------


class TestPythonStrategyCoordinatorInterpreterNotFound:
    def test_interpreter_not_found_logs_warning_returns_coord(self) -> None:
        """When _PythonInterpreter.discover raises PythonInterpreterNotFound,
        a warning is logged and coordinator is returned without configuring path."""
        from serena.refactoring.python_strategy import (
            PythonStrategy,
            PythonInterpreterNotFound,
            _PythonInterpreter,
        )
        from serena.tools.scalpel_runtime import ScalpelRuntime

        mock_server = MagicMock()
        for method_name in AWAITED_SERVER_METHODS:
            getattr(mock_server, method_name)._o2_async_callable = True
        pool = MagicMock()
        pool.acquire.return_value = mock_server

        strategy = PythonStrategy(pool=pool)

        mock_rt = MagicMock()
        mock_rt.dynamic_capability_registry.return_value = DynamicCapabilityRegistry()
        mock_rt.catalog.return_value = None

        with patch.object(
            _PythonInterpreter, "discover",
            side_effect=PythonInterpreterNotFound([(i, "not found") for i in range(1, 15)])
        ), patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            coord = strategy.coordinator(Path("/tmp/py_project"), configure_interpreter=True)

        assert coord is not None
        # basedpyright.configure_python_path should NOT have been called
        mock_server.configure_python_path.assert_not_called()

    def test_configure_interpreter_false_skips_discovery(self) -> None:
        """configure_interpreter=False skips interpreter discovery entirely."""
        from serena.refactoring.python_strategy import PythonStrategy, _PythonInterpreter
        from serena.tools.scalpel_runtime import ScalpelRuntime

        mock_server = MagicMock()
        for method_name in AWAITED_SERVER_METHODS:
            getattr(mock_server, method_name)._o2_async_callable = True
        pool = MagicMock()
        pool.acquire.return_value = mock_server

        strategy = PythonStrategy(pool=pool)

        mock_rt = MagicMock()
        mock_rt.dynamic_capability_registry.return_value = DynamicCapabilityRegistry()
        mock_rt.catalog.return_value = None

        with patch.object(
            _PythonInterpreter, "discover"
        ) as mock_discover, patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            strategy.coordinator(Path("/tmp/py_project"), configure_interpreter=False)

        mock_discover.assert_not_called()


# ---------------------------------------------------------------------------
# find_symbol_position — async paths
# ---------------------------------------------------------------------------


class TestFindSymbolPosition:
    def test_empty_servers_returns_none(self) -> None:
        coord = _make_coord({})
        result = asyncio.run(
            coord.find_symbol_position(
                file="/tmp/test.py",
                name_path="foo",
            )
        )
        assert result is None

    def test_empty_name_path_returns_none(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_position(
                file="/tmp/test.py",
                name_path="",
            )
        )
        assert result is None

    def test_doc_symbol_walk_finds_position(self) -> None:
        """request_document_symbols returns a symbol tree; walk finds the symbol."""
        server = _make_async_server("pylsp-rope")
        # Stub request_document_symbols to return a symbol tree.
        symbols = [
            {
                "name": "foo",
                "selectionRange": {
                    "start": {"line": 5, "character": 3},
                    "end": {"line": 5, "character": 6},
                },
                "range": {
                    "start": {"line": 5, "character": 0},
                    "end": {"line": 10, "character": 0},
                },
                "children": [],
            }
        ]
        server.request_document_symbols.return_value = symbols

        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_position(
                file="/tmp/test.py",
                name_path="foo",
                project_root="/tmp",
            )
        )
        assert result is not None
        assert result["line"] == 5
        assert result["character"] == 3

    def test_doc_symbol_miss_falls_back_to_workspace_symbol(self) -> None:
        """When doc symbols don't contain the name, try workspace_symbol."""
        server = _make_async_server("pylsp-rope")
        # Doc symbols: no "foo"
        server.request_document_symbols.return_value = [
            {"name": "bar", "selectionRange": {"start": {"line": 0, "character": 0}}}
        ]
        # Workspace symbol returns a hit for "foo" in the same file.
        target_path = "/tmp/test.py"
        from pathlib import Path as _Path
        target_uri = _Path(target_path).as_uri()
        server.request_workspace_symbol.return_value = [
            {
                "location": {
                    "uri": target_uri,
                    "range": {
                        "start": {"line": 7, "character": 4},
                        "end": {"line": 7, "character": 7},
                    },
                }
            }
        ]

        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_position(
                file=target_path,
                name_path="foo",
                project_root="/tmp",
            )
        )
        assert result is not None
        assert result["line"] == 7
        assert result["character"] == 4

    def test_workspace_symbol_uri_mismatch_returns_none(self) -> None:
        """If workspace symbol URI doesn't match file, fall through → None."""
        server = _make_async_server("pylsp-rope")
        server.request_document_symbols.return_value = []
        server.request_workspace_symbol.return_value = [
            {
                "location": {
                    "uri": "file:///other/file.py",  # wrong file
                    "range": {
                        "start": {"line": 7, "character": 4},
                        "end": {"line": 7, "character": 7},
                    },
                }
            }
        ]
        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_position(
                file="/tmp/test.py",
                name_path="foo",
                project_root="/tmp",
            )
        )
        assert result is None

    def test_doc_symbol_exception_continues_to_next_server(self) -> None:
        """Server that raises on request_document_symbols is skipped."""
        server1 = _make_async_server("pylsp-rope")
        server1.request_document_symbols.side_effect = RuntimeError("LSP error")
        server1.request_workspace_symbol.return_value = None

        server2 = _make_async_server("basedpyright")
        server2.request_document_symbols.return_value = [
            {
                "name": "foo",
                "selectionRange": {"start": {"line": 1, "character": 0}},
            }
        ]

        coord = _make_coord({"pylsp-rope": server1, "basedpyright": server2})
        result = asyncio.run(
            coord.find_symbol_position(
                file="/tmp/test.py",
                name_path="foo",
                project_root="/tmp",
            )
        )
        assert result is not None
        assert result["line"] == 1


# ---------------------------------------------------------------------------
# find_symbol_range — async paths
# ---------------------------------------------------------------------------


class TestFindSymbolRange:
    def test_empty_servers_returns_none(self) -> None:
        coord = _make_coord({})
        result = asyncio.run(
            coord.find_symbol_range(file="/tmp/test.py", name_path="foo")
        )
        assert result is None

    def test_empty_name_path_returns_none(self) -> None:
        server = _make_async_server("pylsp-rope")
        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_range(file="/tmp/test.py", name_path="")
        )
        assert result is None

    def test_doc_symbol_walk_finds_range(self) -> None:
        server = _make_async_server("pylsp-rope")
        symbols = [
            {
                "name": "MyClass",
                "range": {
                    "start": {"line": 10, "character": 0},
                    "end": {"line": 30, "character": 0},
                },
                "children": [],
            }
        ]
        server.request_document_symbols.return_value = symbols

        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_range(
                file="/tmp/test.py",
                name_path="MyClass",
                project_root="/tmp",
            )
        )
        assert result is not None
        assert result["start"]["line"] == 10
        assert result["end"]["line"] == 30

    def test_doc_symbol_miss_falls_back_to_workspace_symbol(self) -> None:
        server = _make_async_server("pylsp-rope")
        server.request_document_symbols.return_value = [
            {"name": "other_fn", "range": {"start": {"line": 0, "character": 0}}}
        ]
        target_path = "/tmp/test.py"
        from pathlib import Path as _Path
        target_uri = _Path(target_path).as_uri()
        server.request_workspace_symbol.return_value = [
            {
                "location": {
                    "uri": target_uri,
                    "range": {
                        "start": {"line": 5, "character": 0},
                        "end": {"line": 15, "character": 0},
                    },
                }
            }
        ]

        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_range(
                file=target_path,
                name_path="MyClass",
                project_root="/tmp",
            )
        )
        assert result is not None
        assert result["start"]["line"] == 5
        assert result["end"]["line"] == 15

    def test_workspace_symbol_no_end_returns_none(self) -> None:
        """Workspace symbol result with only start (no end) → still falls through."""
        server = _make_async_server("pylsp-rope")
        server.request_document_symbols.return_value = []
        target_path = "/tmp/test.py"
        from pathlib import Path as _Path
        target_uri = _Path(target_path).as_uri()
        # Hit but range has no 'end' key → should not match
        server.request_workspace_symbol.return_value = [
            {
                "location": {
                    "uri": target_uri,
                    "range": {
                        "start": {"line": 5, "character": 0},
                        # no "end"
                    },
                }
            }
        ]
        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_range(
                file=target_path,
                name_path="MyClass",
                project_root="/tmp",
            )
        )
        assert result is None

    def test_server_exception_on_doc_symbols_continues(self) -> None:
        server = _make_async_server("pylsp-rope")
        server.request_document_symbols.side_effect = RuntimeError("no doc symbols")
        server.request_workspace_symbol.return_value = None

        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.find_symbol_range(file="/tmp/test.py", name_path="foo")
        )
        assert result is None


# ---------------------------------------------------------------------------
# request_references — async paths
# ---------------------------------------------------------------------------


class TestRequestReferences:
    def test_empty_servers_returns_empty(self) -> None:
        coord = _make_coord({})
        result = asyncio.run(
            coord.request_references(
                file="/tmp/test.py",
                position={"line": 5, "character": 3},
            )
        )
        assert result == []

    def test_with_position_returns_refs(self) -> None:
        server = _make_async_server("pylsp-rope")
        refs = [
            {"uri": "file:///a.py", "range": {"start": {"line": 1, "character": 0}}},
            {"uri": "file:///b.py", "range": {"start": {"line": 2, "character": 0}}},
        ]
        server.request_references.return_value = refs

        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.request_references(
                file="/tmp/test.py",
                position={"line": 5, "character": 3},
                project_root="/tmp",
            )
        )
        assert len(result) == 2
        assert result[0]["uri"] == "file:///a.py"

    def test_name_path_resolves_position_then_finds_refs(self) -> None:
        """name_path triggers find_symbol_range then request_references."""
        server = _make_async_server("pylsp-rope")
        symbols = [
            {
                "name": "my_func",
                "range": {
                    "start": {"line": 3, "character": 0},
                    "end": {"line": 8, "character": 0},
                },
            }
        ]
        server.request_document_symbols.return_value = symbols
        refs = [
            {"uri": "file:///a.py", "range": {"start": {"line": 1, "character": 0}}}
        ]
        server.request_references.return_value = refs

        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.request_references(
                file="/tmp/test.py",
                name_path="my_func",
                project_root="/tmp",
            )
        )
        assert len(result) == 1

    def test_name_path_not_found_returns_empty(self) -> None:
        """name_path that can't be resolved → empty list."""
        server = _make_async_server("pylsp-rope")
        server.request_document_symbols.return_value = []  # symbol not found
        server.request_workspace_symbol.return_value = None

        coord = _make_coord({"pylsp-rope": server})
        result = asyncio.run(
            coord.request_references(
                file="/tmp/test.py",
                name_path="nonexistent_func",
                project_root="/tmp",
            )
        )
        assert result == []

    def test_server_returns_empty_refs_falls_through(self) -> None:
        """Server returns empty list → try next server."""
        server1 = _make_async_server("pylsp-rope")
        server1.request_references.return_value = []

        server2 = _make_async_server("basedpyright")
        refs = [{"uri": "file:///x.py", "range": {"start": {"line": 0, "character": 0}}}]
        server2.request_references.return_value = refs

        coord = _make_coord({"pylsp-rope": server1, "basedpyright": server2})
        result = asyncio.run(
            coord.request_references(
                file="/tmp/test.py",
                position={"line": 1, "character": 0},
            )
        )
        assert len(result) == 1
        assert result[0]["uri"] == "file:///x.py"

    def test_server_exception_on_request_references_continues(self) -> None:
        server1 = _make_async_server("pylsp-rope")
        server1.request_references.side_effect = RuntimeError("error")

        server2 = _make_async_server("basedpyright")
        server2.request_references.return_value = [
            {"uri": "file:///a.py", "range": {"start": {"line": 0, "character": 0}}}
        ]

        coord = _make_coord({"pylsp-rope": server1, "basedpyright": server2})
        result = asyncio.run(
            coord.request_references(
                file="/tmp/test.py",
                position={"line": 1, "character": 0},
            )
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _walk_document_symbols + _walk_document_symbols_for_range edge cases
# ---------------------------------------------------------------------------


class TestWalkDocumentSymbolsEdgeCases:
    def test_walk_no_children_returns_none_when_rest_nonempty(self) -> None:
        """Searching for a.b where 'a' exists but has no children → None."""
        symbols = [
            {
                "name": "a",
                "selectionRange": {"start": {"line": 0, "character": 0}},
                # no "children" key
            }
        ]
        result = _walk_document_symbols(symbols, ["a", "b"])
        assert result is None

    def test_walk_for_range_returns_none_when_range_missing_fields(self) -> None:
        """Symbol found but range lacks start/end keys → returns None."""
        symbols = [
            {
                "name": "foo",
                "range": {},  # empty range
            }
        ]
        result = _walk_document_symbols_for_range(symbols, ["foo"])
        assert result is None

    def test_walk_for_range_uses_selection_range_fallback(self) -> None:
        """When 'range' is absent, falls back to 'selectionRange'."""
        symbols = [
            {
                "name": "foo",
                "selectionRange": {
                    "start": {"line": 2, "character": 1},
                    "end": {"line": 2, "character": 4},
                },
                # no "range" key
            }
        ]
        result = _walk_document_symbols_for_range(symbols, ["foo"])
        assert result is not None
        assert result["start"]["line"] == 2

    def test_walk_nested_symbols_found(self) -> None:
        """Walk nested hierarchy a::b using list of two segments."""
        symbols = [
            {
                "name": "a",
                "selectionRange": {"start": {"line": 0, "character": 0}},
                "children": [
                    {
                        "name": "b",
                        "selectionRange": {
                            "start": {"line": 5, "character": 4},
                            "end": {"line": 5, "character": 5},
                        },
                        "children": [],
                    }
                ],
            }
        ]
        result = _walk_document_symbols(symbols, ["a", "b"])
        assert result is not None
        assert result["line"] == 5

    def test_walk_for_range_nested_found(self) -> None:
        symbols = [
            {
                "name": "MyClass",
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 20, "character": 0},
                },
                "children": [
                    {
                        "name": "method",
                        "range": {
                            "start": {"line": 5, "character": 4},
                            "end": {"line": 10, "character": 4},
                        },
                        "children": [],
                    }
                ],
            }
        ]
        result = _walk_document_symbols_for_range(symbols, ["MyClass", "method"])
        assert result is not None
        assert result["start"]["line"] == 5
        assert result["end"]["line"] == 10

    def test_walk_non_list_node_handled(self) -> None:
        """Non-list nodes arg (e.g. a dict) is wrapped to list."""
        node = {
            "name": "foo",
            "selectionRange": {"start": {"line": 0, "character": 0}},
        }
        result = _walk_document_symbols(node, ["foo"])
        assert result is not None

    def test_walk_skips_non_dict_entries(self) -> None:
        """Non-dict entries in symbols list are skipped."""
        symbols = ["not_a_dict", None, {"name": "foo", "selectionRange": {"start": {"line": 1, "character": 0}}}]
        result = _walk_document_symbols(symbols, ["foo"])
        assert result is not None
        assert result["line"] == 1
