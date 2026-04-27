"""v0.2.0-C — MultiServerCoordinator.find_symbol_position real implementation.

Backlog item #3 from MVP cut. Replaces the text-search fallback in
``scalpel_facades._resolve_symbol_position`` with a real LSP-driven lookup
that walks ``request_document_symbols`` hierarchically by name_path
segments (``.`` for Python, ``::`` for Rust) and falls back to
``request_workspace_symbol`` when the document-level walk misses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.refactoring._async_check import AWAITED_SERVER_METHODS
from serena.refactoring.multi_server import MultiServerCoordinator


def _mark_async_callable(server: MagicMock) -> MagicMock:
    """Stamp the ``_o2_async_callable`` marker on every awaited method.

    ``MultiServerCoordinator.__init__`` runs ``assert_servers_async_callable``
    which now requires Mocks to opt-in via the ``_o2_async_callable=True``
    marker (TRIZ separation: production gate must reject accidental Mocks).
    Test doubles that intentionally back the coordinator must declare intent.
    """
    for method_name in AWAITED_SERVER_METHODS:
        getattr(server, method_name)._o2_async_callable = True
    return server


def _doc_symbol(name: str, line: int, character: int, children: list[Any] | None = None):
    """Mimic the SolidLanguageServer DocumentSymbol shape (LSP)."""
    return {
        "name": name,
        "kind": 12,  # function
        "range": {
            "start": {"line": line, "character": character},
            "end": {"line": line, "character": character + len(name)},
        },
        "selectionRange": {
            "start": {"line": line, "character": character},
            "end": {"line": line, "character": character + len(name)},
        },
        "children": children or [],
    }


def _make_coord_with_doc_symbols(symbols, server_id="pylsp-rope"):
    """Build a coordinator with a single async server whose
    ``request_document_symbols`` returns ``symbols`` (sync — wrapped here)."""
    server = MagicMock()
    server.request_document_symbols = MagicMock(return_value=symbols)
    server.request_workspace_symbol = MagicMock(return_value=None)
    _mark_async_callable(server)
    return MultiServerCoordinator(servers={server_id: server})


@pytest.mark.asyncio
async def test_find_symbol_position_top_level_python_function(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text("def alpha(): ...\n")
    coord = _make_coord_with_doc_symbols([_doc_symbol("alpha", line=0, character=4)])
    pos = await coord.find_symbol_position(file=str(file), name_path="alpha")
    assert pos == {"line": 0, "character": 4}


@pytest.mark.asyncio
async def test_find_symbol_position_nested_python_method(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text("class C:\n    def m(self): ...\n")
    coord = _make_coord_with_doc_symbols([
        _doc_symbol("C", line=0, character=6, children=[
            _doc_symbol("m", line=1, character=8),
        ]),
    ])
    pos = await coord.find_symbol_position(file=str(file), name_path="C.m")
    assert pos == {"line": 1, "character": 8}


@pytest.mark.asyncio
async def test_find_symbol_position_rust_path_uses_double_colon(tmp_path: Path):
    file = tmp_path / "lib.rs"
    file.write_text("mod inner { pub fn beta() {} }\n")
    coord = _make_coord_with_doc_symbols([
        _doc_symbol("inner", line=0, character=4, children=[
            _doc_symbol("beta", line=0, character=19),
        ]),
    ], server_id="rust-analyzer")
    pos = await coord.find_symbol_position(file=str(file), name_path="inner::beta")
    assert pos == {"line": 0, "character": 19}


@pytest.mark.asyncio
async def test_find_symbol_position_returns_none_when_missing(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text("\n")
    coord = _make_coord_with_doc_symbols([_doc_symbol("other", line=0, character=4)])
    pos = await coord.find_symbol_position(file=str(file), name_path="missing")
    assert pos is None


@pytest.mark.asyncio
async def test_find_symbol_position_falls_back_to_workspace_symbol(
    tmp_path: Path,
):
    """When document-level walk misses, try workspace_symbol with the
    last name-path segment and accept results scoped to ``file``."""
    file = tmp_path / "lib.py"
    file.write_text("\n")
    server = MagicMock()
    server.request_document_symbols = MagicMock(return_value=[])
    server.request_workspace_symbol = MagicMock(return_value=[
        {
            "name": "gamma",
            "location": {
                "uri": file.as_uri(),
                "range": {
                    "start": {"line": 5, "character": 0},
                    "end": {"line": 5, "character": 5},
                },
            },
        },
    ])
    _mark_async_callable(server)
    coord = MultiServerCoordinator(servers={"pylsp-rope": server})
    pos = await coord.find_symbol_position(file=str(file), name_path="gamma")
    assert pos == {"line": 5, "character": 0}


@pytest.mark.asyncio
async def test_find_symbol_position_workspace_filter_rejects_other_files(
    tmp_path: Path,
):
    target = tmp_path / "lib.py"
    target.write_text("\n")
    other = tmp_path / "other.py"
    other.write_text("\n")
    server = MagicMock()
    server.request_document_symbols = MagicMock(return_value=[])
    server.request_workspace_symbol = MagicMock(return_value=[
        {"name": "gamma",
         "location": {"uri": other.as_uri(),
                      "range": {"start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0}}}},
    ])
    _mark_async_callable(server)
    coord = MultiServerCoordinator(servers={"pylsp-rope": server})
    pos = await coord.find_symbol_position(file=str(target), name_path="gamma")
    assert pos is None


@pytest.mark.asyncio
async def test_find_symbol_position_relative_to_project_root(
    tmp_path: Path,
):
    """Coordinator passes a project-root-relative path to the LSP server."""
    project = tmp_path / "proj"
    project.mkdir()
    src = project / "pkg" / "mod.py"
    src.parent.mkdir()
    src.write_text("\n")
    server = MagicMock()
    server.request_document_symbols = MagicMock(return_value=[])
    server.request_workspace_symbol = MagicMock(return_value=None)
    _mark_async_callable(server)
    coord = MultiServerCoordinator(servers={"pylsp-rope": server})
    await coord.find_symbol_position(
        file=str(src), name_path="x", project_root=str(project),
    )
    call_args = server.request_document_symbols.call_args
    rel = call_args.args[0] if call_args.args else call_args.kwargs.get("relative_file_path")
    assert rel == "pkg/mod.py"
