"""Stage 2A T4 — ExtractTool tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ExtractTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(project_root: Path) -> ExtractTool:
    tool = ExtractTool.__new__(ExtractTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_extract_function_rust_calls_coordinator(tmp_path):
    target = tmp_path / "lib.rs"
    target.write_text("pub fn x() { let a = 1 + 2; }\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):
        assert kwargs["only"] == ["refactor.extract.function"]
        return [MagicMock(action_id="ra:1", title="extract", kind="refactor.extract.function",
                          provenance="rust-analyzer")]
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            range={"start": {"line": 0, "character": 16},
                   "end": {"line": 0, "character": 22}},
            target="function",
            new_name="add_one_two",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["checkpoint_id"] is not None


def test_extract_variable_python_uses_extract_variable_kind(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("def f(): return 1 + 2\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):
        assert kwargs["only"] == ["refactor.extract.variable"]
        return [MagicMock(action_id="rope:1", title="x", kind="refactor.extract.variable",
                          provenance="pylsp-rope")]
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            range={"start": {"line": 0, "character": 16},
                   "end": {"line": 0, "character": 21}},
            target="variable",
            new_name="result",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_extract_requires_range_or_name_path(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("\n")
    tool = _make_tool(tmp_path)
    out = tool.apply(
        file=str(target), target="function", language="python",
    )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_extract_no_actions_returns_symbol_not_found(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("def f(): pass\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):  # noqa: ARG001
        return []
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            range={"start": {"line": 0, "character": 0},
                   "end": {"line": 0, "character": 1}},
            target="function", language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


def test_extract_workspace_boundary_violation_blocked(tmp_path):
    tool = _make_tool(tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.py"),
        range={"start": {"line": 0, "character": 0},
               "end": {"line": 0, "character": 1}},
        target="function", language="python",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


# ---------------------------------------------------------------------------
# v1.5 G7-C — sibling real-disk acid test.
#
# The mock-only tests above assert dispatch shape only. This sibling
# extends the discipline: tmp_path workspace + mock coord whose
# resolved WorkspaceEdit lands actual content on disk.
# ---------------------------------------------------------------------------


def test_extract_function_real_disk_lands_new_function_on_disk(tmp_path):
    """Acid-test sibling: extract function from `1 + 2` selection;
    assert the WorkspaceEdit's resolved newText reaches disk."""
    target = tmp_path / "lib.rs"
    target.write_text("pub fn x() { let a = 1 + 2; }\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):
        assert kwargs["only"] == ["refactor.extract.function"]
        return [MagicMock(
            action_id="ra:1", id="ra:1", title="extract",
            kind="refactor.extract.function", provenance="rust-analyzer",
            is_preferred=False,
        )]

    fake_coord.merge_code_actions = _merge
    fake_coord.get_action_edit = lambda _aid: {
        "changes": {
            target.as_uri(): [{
                "range": {
                    "start": {"line": 0, "character": 21},
                    "end": {"line": 0, "character": 26},
                },
                "newText": "add_one_two()",
            }, {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 0},
                },
                "newText": "fn add_one_two() -> i32 { 1 + 2 }\n",
            }],
        },
    }
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            range={"start": {"line": 0, "character": 21},
                   "end": {"line": 0, "character": 26}},
            target="function",
            new_name="add_one_two",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    after = target.read_text(encoding="utf-8")
    assert after != before
    assert "fn add_one_two()" in after
    assert "add_one_two()" in after


def test_extract_dry_run_no_checkpoint(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("def f(): return 1+2\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):  # noqa: ARG001
        return [MagicMock(action_id="rope:1", title="x", kind="refactor.extract.variable",
                          provenance="pylsp-rope")]
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            range={"start": {"line": 0, "character": 16},
                   "end": {"line": 0, "character": 19}},
            target="variable", language="python", dry_run=True,
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"] is not None
    assert payload["checkpoint_id"] is None
