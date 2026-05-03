"""v1.5 G8 — LO-1: rename also_in_strings honest warning.

textDocument/rename cannot rewrite string literals. When the caller
passes also_in_strings=True, the response should carry a warning that
points to scalpel_replace_regex as the right tool — instead of silently
ignoring the flag.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import RenameTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "lib.rs"
    src.write_text(
        'pub fn helper() {}\n'
        'fn caller() { let s = "helper called"; helper(); }\n'
    )
    return tmp_path


def _make_tool(project_root: Path) -> RenameTool:
    tool = RenameTool.__new__(RenameTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_rename_also_in_strings_emits_warning(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_method.return_value = True

    async def _find(**_kw):
        return {"line": 0, "character": 7}
    fake_coord.find_symbol_position = _find

    async def _rename(**_kw):
        return ({"changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 7},
                      "end": {"line": 0, "character": 13}},
            "newText": "renamed",
        }]}}, [])
    fake_coord.merge_rename = _rename

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            name_path="helper",
            new_name="renamed",
            also_in_strings=True,
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    warnings = payload.get("warnings") or ()
    # Warning is present:
    assert any(
        "also_in_strings" in w and "scalpel_replace_regex" in w
        for w in warnings
    ), warnings
    # String literal was NOT rewritten (correct LSP semantics):
    body = src.read_text(encoding="utf-8")
    assert '"helper called"' in body


def test_rename_without_also_in_strings_no_warning(rust_workspace):
    """Counter-test: when also_in_strings=False, no warning is emitted."""
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_method.return_value = True

    async def _find(**_kw):
        return {"line": 0, "character": 7}
    fake_coord.find_symbol_position = _find

    async def _rename(**_kw):
        return ({"changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 7},
                      "end": {"line": 0, "character": 13}},
            "newText": "renamed",
        }]}}, [])
    fake_coord.merge_rename = _rename

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            name_path="helper",
            new_name="renamed",
            also_in_strings=False,
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    warnings = payload.get("warnings") or ()
    assert not any("also_in_strings" in w for w in warnings)
