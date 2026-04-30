"""v1.5 G4-7 — scalpel_inline honors name_path + remove_definition;
no (0,0) fallback (HI-8 + HI-13).

Acid tests:
  * name_path is no longer dropped — coord.find_symbol_range supplies
    the position when caller passes name_path instead of position.
  * remove_definition=False post-filters the WorkspaceEdit so the
    definition deletion hunk is dropped while the call-site rewrite
    still applies.
  * scope='all_callers' triggers references-driven dispatch (NOT a
    silent (0,0) fallback) — one inline per call site.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ScalpelInlineTool
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
        "fn helper(a: i32) -> i32 { a + 1 }\n"
        "fn caller() { let x = helper(10); }\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_tool(project_root: Path) -> Any:
    tool = ScalpelInlineTool.__new__(ScalpelInlineTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str, kind: str):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.kind = kind
    a.is_preferred = False
    a.provenance = "rust-analyzer"
    return a


def test_inline_resolves_name_path_to_position(rust_workspace):
    """name_path is no longer dropped; coord.find_symbol_range supplies
    the position (and the dispatch never uses (0,0))."""
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _find(**kw):
        return {"start": {"line": 1, "character": 22},
                "end": {"line": 1, "character": 32}}

    fake_coord.find_symbol_range = _find

    async def _actions(**kw):
        captured.append(kw)
        return [_action("ra:1", "Inline call", "refactor.inline.call")]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {src.as_uri(): [{
        "range": {"start": {"line": 1, "character": 22},
                  "end": {"line": 1, "character": 32}},
        "newText": "10 + 1",
    }]}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            name_path="caller::helper",   # NOT position=
            target="call",
            scope="single_call_site",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    body = src.read_text(encoding="utf-8")
    assert "helper(10)" not in body
    assert "10 + 1" in body
    # Dispatch used resolved range, NOT (0,0):
    assert captured, "no merge_code_actions call captured"
    for c in captured:
        assert c["start"] != {"line": 0, "character": 0}


def test_inline_remove_definition_false_keeps_definition(rust_workspace):
    """When the LSP emits both 'replace call' and 'delete definition'
    hunks, remove_definition=False post-filters out the deletion."""
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _find(**kw):
        return {"start": {"line": 1, "character": 22},
                "end": {"line": 1, "character": 32}}

    fake_coord.find_symbol_range = _find

    async def _actions(**kw):
        return [_action("ra:1", "Inline call", "refactor.inline.call")]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {src.as_uri(): [
        # Hunk 1: replace call site
        {"range": {"start": {"line": 1, "character": 22},
                   "end": {"line": 1, "character": 32}},
         "newText": "10 + 1"},
        # Hunk 2: delete definition (the bit we want to KEEP).
        # This is a multi-line empty-newText hunk (heuristic: definition
        # deletion).
        {"range": {"start": {"line": 0, "character": 0},
                   "end": {"line": 1, "character": 0}},
         "newText": ""},
    ]}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 1, "character": 22},
            target="call",
            scope="single_call_site",
            remove_definition=False,
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    body = src.read_text(encoding="utf-8")
    # Definition preserved (because remove_definition=False filtered the
    # deletion hunk):
    assert "fn helper(a: i32)" in body
    # Call site still inlined:
    assert "10 + 1" in body


def test_inline_all_callers_uses_references_not_zero_zero(rust_workspace):
    """scope='all_callers' triggers references-driven dispatch, NOT a
    silent (0,0) fallback. The facade calls coord.request_references and
    iterates one inline per returned location."""
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _find(**kw):
        return {"start": {"line": 0, "character": 3},
                "end": {"line": 0, "character": 9}}

    fake_coord.find_symbol_range = _find

    captured: list[dict] = []

    async def _references(**kw):
        return [
            {"uri": src.as_uri(),
             "range": {"start": {"line": 1, "character": 22},
                       "end": {"line": 1, "character": 32}}},
        ]

    fake_coord.request_references = _references

    async def _actions(**kw):
        captured.append(kw)
        return [_action("ra:1", "Inline call", "refactor.inline.call")]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {"changes": {src.as_uri(): [{
        "range": {"start": {"line": 1, "character": 22},
                  "end": {"line": 1, "character": 32}},
        "newText": "10 + 1",
    }]}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            name_path="helper",
            target="call",
            scope="all_callers",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    # Dispatch happened against the reference position, NOT (0,0):
    assert captured, "no merge_code_actions call captured"
    for c in captured:
        assert c["start"] != {"line": 0, "character": 0}
