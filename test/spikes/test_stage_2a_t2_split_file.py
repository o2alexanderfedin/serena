"""Stage 2A T3 — ScalpelSplitFileTool tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ScalpelSplitFileTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def python_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "calcpy.py"
    src.write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def sub(a, b):\n    return a - b\n"
    )
    return tmp_path


def _make_tool(project_root: Path) -> ScalpelSplitFileTool:
    tool = ScalpelSplitFileTool.__new__(ScalpelSplitFileTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_split_file_python_groups_dispatches_rope_per_group(python_workspace):
    tool = _make_tool(python_workspace)
    fake_bridge = MagicMock()
    fake_bridge.move_module.return_value = {"documentChanges": [
        {"textDocument": {"uri": "file:///x.py", "version": None},
         "edits": [{"range": {"start": {"line": 0, "character": 0},
                              "end": {"line": 1, "character": 0}}, "newText": "x"}]}
    ]}
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        out = tool.apply(
            file=str(python_workspace / "calcpy.py"),
            groups={"add_only": ["add"]},
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["checkpoint_id"] is not None
    assert fake_bridge.move_module.call_count >= 1


def test_split_file_rejects_out_of_workspace(tmp_path):
    tool = _make_tool(tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.py"),
        groups={"a": ["foo"]},
        language="python",
    )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


def test_split_file_dry_run_returns_preview_token(python_workspace):
    tool = _make_tool(python_workspace)
    fake_bridge = MagicMock()
    fake_bridge.move_module.return_value = {"documentChanges": []}
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        out = tool.apply(
            file=str(python_workspace / "calcpy.py"),
            groups={"a": ["add"]},
            language="python",
            dry_run=True,
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"] is not None


def test_split_file_unknown_language_fails(python_workspace):
    tool = _make_tool(python_workspace)
    out = tool.apply(
        file=str(python_workspace / "calcpy.unknown_ext"),
        groups={"a": ["add"]},
        language=None,
    )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_split_file_empty_groups_is_no_op(python_workspace):
    tool = _make_tool(python_workspace)
    out = tool.apply(
        file=str(python_workspace / "calcpy.py"),
        groups={},
        language="python",
    )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["no_op"] is True


def test_split_file_rust_dispatches_coordinator(python_workspace):
    target = python_workspace / "lib.rs"
    target.write_text("pub fn add() {}\npub fn sub() {}\n")
    tool = _make_tool(python_workspace)
    fake_coord = MagicMock()

    async def _fake_merge(**kwargs):  # noqa: ARG001
        return [
            MagicMock(
                action_id="ra:1",
                title="Move to module",
                kind="refactor.extract.module",
                provenance="rust-analyzer",
            )
        ]
    fake_coord.merge_code_actions = _fake_merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            groups={"helpers": ["add"]},
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
