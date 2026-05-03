"""v1.5 G4-6 — extract honors new_name / visibility / similar / global_scope (HI-7).

Acid tests:
  * Rust: `new_name` post-processes the WorkspaceEdit replacing rust-analyzer's
    auto-name (`new_function`, `new_var`, etc.) with the caller's
    `new_name`. Real-disk Path.read_text() asserts the new name landed.
  * Rust: `visibility="pub_crate"` post-processes the emitted hunks to
    inject ``pub(crate)`` before the bare ``fn``/``const``/``type``
    keyword on the new item.
  * Python (rope): `similar=True` flows through ``merge_code_actions``'s
    additive ``arguments=`` payload and rope's per-server invocation
    captures it.
  * Python (rope): `global_scope=True` flows through the same payload.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ExtractTool
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
        "fn caller() { let x = 1 + 2 + 3; }\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def python_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "calc.py"
    src.write_text(
        "def caller():\n    x = 1 + 2 + 3\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_tool(project_root: Path) -> Any:
    tool = ExtractTool.__new__(ExtractTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str, *, kind: str, provenance: str = "rust-analyzer"):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.kind = kind
    a.is_preferred = False
    a.provenance = provenance
    return a


def test_rust_extract_post_processes_new_name(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return [_action("ra:1", "Extract function",
                        kind="refactor.extract.function")]

    fake_coord.merge_code_actions = _actions

    fake_coord.get_action_edit = lambda aid: {
        "changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 1, "character": 0}},
            "newText": (
                "fn caller() { let x = new_function(); }\n"
                "fn new_function() -> i32 { 1 + 2 + 3 }\n"
            ),
        }]},
    }

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            range={"start": {"line": 0, "character": 23},
                   "end": {"line": 0, "character": 31}},
            target="function",
            new_name="sum_three",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    body = src.read_text(encoding="utf-8")
    assert "sum_three" in body
    assert "new_function" not in body


def test_rust_extract_post_processes_visibility_pub_crate(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return [_action("ra:1", "Extract function",
                        kind="refactor.extract.function")]

    fake_coord.merge_code_actions = _actions

    fake_coord.get_action_edit = lambda aid: {
        "changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 1, "character": 0}},
            "newText": (
                "fn caller() { let x = new_function(); }\n"
                "fn new_function() -> i32 { 1 + 2 + 3 }\n"
            ),
        }]},
    }

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            range={"start": {"line": 0, "character": 23},
                   "end": {"line": 0, "character": 31}},
            target="function",
            new_name="sum",
            visibility="pub_crate",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    body = src.read_text(encoding="utf-8")
    assert "pub(crate) fn sum" in body


def test_python_extract_passes_similar_in_arguments_payload(python_workspace):
    """Asserts the dispatch's ``arguments`` payload carries similar=True."""
    tool = _make_tool(python_workspace)
    src = python_workspace / "calc.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        return [_action("rope:1", "Extract method",
                        kind="refactor.extract.function",
                        provenance="pylsp-rope")]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {
        "changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 0, "character": 0}},
            "newText": "",
        }]},
    }

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            range={"start": {"line": 1, "character": 8},
                   "end": {"line": 1, "character": 17}},
            target="function",
            new_name="sum_three",
            similar=True,
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    # The dispatch's arguments-payload carries similar=True:
    args = [c.get("arguments") for c in captured]
    assert any(
        isinstance(a, list) and a and a[0].get("similar") is True
        for a in args
    ), captured


def test_python_extract_passes_global_scope_in_arguments_payload(python_workspace):
    tool = _make_tool(python_workspace)
    src = python_workspace / "calc.py"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured: list[dict] = []

    async def _actions(**kw):
        captured.append(kw)
        return [_action("rope:1", "Extract variable",
                        kind="refactor.extract.variable",
                        provenance="pylsp-rope")]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {
        "changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 0, "character": 0}},
            "newText": "",
        }]},
    }

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            range={"start": {"line": 1, "character": 8},
                   "end": {"line": 1, "character": 17}},
            target="variable",
            new_name="threes",
            global_scope=True,
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    args = [c.get("arguments") for c in captured]
    assert any(
        isinstance(a, list) and a and a[0].get("global_scope") is True
        for a in args
    ), captured
