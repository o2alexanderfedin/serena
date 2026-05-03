"""Unit tests for ``MultiServerCoordinator.find_symbol_range``.

Sibling to the v0.2.0-C ``find_symbol_position`` tests. Where
``find_symbol_position`` returns just the symbol's selection-range start,
``find_symbol_range`` returns the symbol's full body span (LSP ``range``),
which ``extract`` requires when only ``name_path`` is supplied.
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

    Mirrors the helper in ``test_v0_2_0_c_find_symbol_position.py``.
    """
    for method_name in AWAITED_SERVER_METHODS:
        getattr(server, method_name)._o2_async_callable = True
    return server


def _doc_symbol(
    name: str,
    line: int,
    character: int,
    *,
    end_line: int | None = None,
    end_character: int | None = None,
    children: list[Any] | None = None,
) -> dict[str, Any]:
    """Mimic the LSP DocumentSymbol shape with distinct range vs selectionRange.

    ``range`` covers the full symbol body; ``selectionRange`` covers just the
    name. The new helper must return ``range``, not ``selectionRange``.
    """
    end_l = end_line if end_line is not None else line + 5
    end_c = end_character if end_character is not None else 0
    return {
        "name": name,
        "kind": 12,  # function
        "range": {
            "start": {"line": line, "character": character},
            "end": {"line": end_l, "character": end_c},
        },
        "selectionRange": {
            "start": {"line": line, "character": character},
            "end": {"line": line, "character": character + len(name)},
        },
        "children": children or [],
    }


def _make_coord_with_doc_symbols(
    symbols: list[dict[str, Any]], server_id: str = "pylsp-rope",
) -> MultiServerCoordinator:
    server = MagicMock()
    server.request_document_symbols = MagicMock(return_value=symbols)
    server.request_workspace_symbol = MagicMock(return_value=None)
    _mark_async_callable(server)
    return MultiServerCoordinator(servers={server_id: server})


@pytest.mark.asyncio
async def test_find_symbol_range_top_level_python_function(tmp_path: Path) -> None:
    """Top-level symbol — full body range returned (not just selectionRange)."""
    file = tmp_path / "module.py"
    file.write_text("def alpha():\n    return 1\n")
    coord = _make_coord_with_doc_symbols([
        _doc_symbol("alpha", line=0, character=4, end_line=1, end_character=12),
    ])
    rng = await coord.find_symbol_range(file=str(file), name_path="alpha")
    assert rng == {
        "start": {"line": 0, "character": 4},
        "end": {"line": 1, "character": 12},
    }


@pytest.mark.asyncio
async def test_find_symbol_range_nested_python_method(tmp_path: Path) -> None:
    """Nested symbols are reachable via the dotted name-path."""
    file = tmp_path / "module.py"
    file.write_text("class C:\n    def m(self):\n        return 1\n")
    coord = _make_coord_with_doc_symbols([
        _doc_symbol("C", line=0, character=6, end_line=2, end_character=16, children=[
            _doc_symbol("m", line=1, character=8, end_line=2, end_character=16),
        ]),
    ])
    rng = await coord.find_symbol_range(file=str(file), name_path="C.m")
    assert rng == {
        "start": {"line": 1, "character": 8},
        "end": {"line": 2, "character": 16},
    }


@pytest.mark.asyncio
async def test_find_symbol_range_rust_path_uses_double_colon(tmp_path: Path) -> None:
    """``::``-separated name-paths drill into Rust mod hierarchies."""
    file = tmp_path / "lib.rs"
    file.write_text("mod inner { pub fn beta() {} }\n")
    coord = _make_coord_with_doc_symbols([
        _doc_symbol("inner", line=0, character=4, end_line=0, end_character=30, children=[
            _doc_symbol("beta", line=0, character=19, end_line=0, end_character=29),
        ]),
    ], server_id="rust-analyzer")
    rng = await coord.find_symbol_range(file=str(file), name_path="inner::beta")
    assert rng == {
        "start": {"line": 0, "character": 19},
        "end": {"line": 0, "character": 29},
    }


@pytest.mark.asyncio
async def test_find_symbol_range_returns_none_when_missing(tmp_path: Path) -> None:
    file = tmp_path / "module.py"
    file.write_text("\n")
    coord = _make_coord_with_doc_symbols([
        _doc_symbol("other", line=0, character=4),
    ])
    rng = await coord.find_symbol_range(file=str(file), name_path="missing")
    assert rng is None


@pytest.mark.asyncio
async def test_find_symbol_range_falls_back_to_workspace_symbol(
    tmp_path: Path,
) -> None:
    """When document-walk misses, workspace_symbol's location.range is used."""
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
                    "end": {"line": 7, "character": 4},
                },
            },
        },
    ])
    _mark_async_callable(server)
    coord = MultiServerCoordinator(servers={"pylsp-rope": server})
    rng = await coord.find_symbol_range(file=str(file), name_path="gamma")
    assert rng == {
        "start": {"line": 5, "character": 0},
        "end": {"line": 7, "character": 4},
    }


@pytest.mark.asyncio
async def test_find_symbol_range_falls_back_selection_when_range_missing(
    tmp_path: Path,
) -> None:
    """If a symbol carries only ``selectionRange``, that span is returned."""
    file = tmp_path / "module.py"
    file.write_text("\n")
    sel_only = {
        "name": "delta",
        "kind": 12,
        "selectionRange": {
            "start": {"line": 3, "character": 4},
            "end": {"line": 3, "character": 9},
        },
        "children": [],
    }
    coord = _make_coord_with_doc_symbols([sel_only])
    rng = await coord.find_symbol_range(file=str(file), name_path="delta")
    assert rng == {
        "start": {"line": 3, "character": 4},
        "end": {"line": 3, "character": 9},
    }
