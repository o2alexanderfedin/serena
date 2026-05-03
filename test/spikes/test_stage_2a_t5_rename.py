"""Stage 2A T6 — RenameTool tests."""
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


def _make_tool(project_root: Path) -> RenameTool:
    tool = RenameTool.__new__(RenameTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_rename_dispatches_merge_rename(tmp_path):
    target = tmp_path / "lib.rs"
    target.write_text("pub struct Engine;\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge_rename(relative_file_path, line, column, new_name, language="python"):
        del relative_file_path, line, column, language
        assert new_name == "Core"
        return ({"changes": {target.as_uri(): []}}, [])
    fake_coord.merge_rename = _merge_rename

    async def _find_pos(**kwargs):  # noqa: ARG001
        return {"line": 0, "character": 11}
    fake_coord.find_symbol_position = _find_pos
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            name_path="Engine",
            new_name="Core",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["checkpoint_id"] is not None


def test_rename_python_module_uses_rope_bridge(tmp_path):
    src = tmp_path / "old_mod.py"
    src.write_text("x = 1\n")
    tool = _make_tool(tmp_path)
    fake_bridge = MagicMock()
    fake_bridge.move_module.return_value = {"documentChanges": [
        {"kind": "rename",
         "oldUri": src.as_uri(),
         "newUri": (tmp_path / "new_mod.py").as_uri()}
    ]}
    with patch(
        "serena.tools.scalpel_facades._build_python_rope_bridge",
        return_value=fake_bridge,
    ):
        out = tool.apply(
            file=str(src),
            name_path="old_mod",
            new_name="new_mod",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    fake_bridge.move_module.assert_called_once_with("old_mod.py", "new_mod.py")


def test_rename_unknown_symbol_returns_symbol_not_found(tmp_path):
    target = tmp_path / "x.py"
    target.write_text("\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _find_pos(**kwargs):  # noqa: ARG001
        return None
    fake_coord.find_symbol_position = _find_pos
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            name_path="nope",
            new_name="alsoNope",
            language="python",
        )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------------------------------------------------------------------------
# v1.5 G7-C — sibling real-disk acid test.
# ---------------------------------------------------------------------------


def test_rename_real_disk_lands_new_name_on_disk(tmp_path):
    """G7-C acid test — sibling of test_*_real_disk_lands_* in G7-A/B.

    RenameTool.apply MUST invoke
    ``_apply_workspace_edit_to_disk(workspace_edit)`` so that
    ``Path.read_text()`` post-apply reflects the rename. Pre-v1.5
    cleanup the call was missing (see deferred-items.md "Wave 4
    discovery"); this test pins down the fixed behavior matching the
    other 9 G7-A/B siblings (``after != before``).

    Discipline: the acid is on observable disk state, not on the
    response envelope alone — decorative ``applied=True`` without disk
    mutation is exactly the class of bug the v1.5 milestone closes.
    """
    target = tmp_path / "lib.rs"
    target.write_text("pub struct Engine;\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    edit = {
        "changes": {
            target.as_uri(): [{
                "range": {
                    "start": {"line": 0, "character": 11},
                    "end": {"line": 0, "character": 17},
                },
                "newText": "Core",
            }],
        },
    }

    async def _merge_rename(relative_file_path, line, column, new_name, language="python"):
        del relative_file_path, line, column, new_name, language
        return (edit, [])

    fake_coord.merge_rename = _merge_rename

    async def _find_pos(**_kw):
        return {"line": 0, "character": 11}

    fake_coord.find_symbol_position = _find_pos
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            name_path="Engine",
            new_name="Core",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload.get("checkpoint_id") is not None
    after = target.read_text(encoding="utf-8")
    # The acid: the file must actually change on disk. Prior to the
    # G7-C fix, the WorkspaceEdit was only recorded in the checkpoint
    # without being routed through ``_apply_workspace_edit_to_disk``.
    assert after != before
    assert "Core" in after
    assert "Engine" not in after


def test_rename_workspace_boundary_blocked(tmp_path):
    tool = _make_tool(tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.py"),
        name_path="x", new_name="y", language="python",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


def test_rename_dry_run_no_checkpoint(tmp_path):
    target = tmp_path / "lib.rs"
    target.write_text("pub struct Engine;\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge_rename(relative_file_path, line, column, new_name, language="python"):
        del relative_file_path, line, column, new_name, language
        return ({"changes": {}}, [])
    fake_coord.merge_rename = _merge_rename

    async def _find_pos(**kwargs):  # noqa: ARG001
        return {"line": 0, "character": 0}
    fake_coord.find_symbol_position = _find_pos
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target), name_path="Engine", new_name="Core",
            language="rust", dry_run=True,
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"] is not None
    assert payload["checkpoint_id"] is None
