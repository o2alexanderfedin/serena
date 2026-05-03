"""Stage 2A T3 — SplitFileTool tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import SplitFileTool
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


def _make_tool(project_root: Path) -> SplitFileTool:
    tool = SplitFileTool.__new__(SplitFileTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_split_file_python_groups_dispatches_rope_per_group(python_workspace):
    """v1.9.1 Item B — non-empty symbol list dispatches per-symbol via
    ``bridge.move_global``. (Pre-v1.9.1 this test asserted ``move_module``;
    the v1.6 contract treated symbol lists as informational and moved the
    whole module.)
    """
    tool = _make_tool(python_workspace)
    fake_bridge = MagicMock()
    fake_bridge.move_global.return_value = {"documentChanges": [
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
    assert fake_bridge.move_global.call_count >= 1
    fake_bridge.move_module.assert_not_called()


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
    fake_coord.supports_kind.return_value = True

    async def _fake_find(file, name_path, project_root):  # noqa: ARG001
        # v1.5 G3a — _split_rust now resolves each symbol's range before
        # dispatching one extract.module per symbol. Return a non-(0,0)
        # body span so the dispatch-shape assertion below still holds.
        return {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 15},
        }

    fake_coord.find_symbol_range = _fake_find

    async def _fake_merge(**kwargs):  # noqa: ARG001
        return [
            MagicMock(
                action_id="ra:1",
                id="ra:1",
                title="Move to module",
                kind="refactor.extract.module",
                provenance="rust-analyzer",
                is_preferred=False,
            )
        ]
    fake_coord.merge_code_actions = _fake_merge
    fake_coord.get_action_edit = lambda aid: {"changes": {}}
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


# ---------------------------------------------------------------------------
# v1.5 G7-C — sibling real-disk acid test for the rust split path.
#
# The mock-only test above asserts dispatch shape only. This sibling
# extends the discipline: tmp_path workspace + mock coord whose
# resolved WorkspaceEdit lands actual content on disk. Pattern mirrors
# test_v1_5_g7a_rust_real_disk.py.
# ---------------------------------------------------------------------------


def test_split_file_rust_real_disk_per_group_mutation(python_workspace):
    """Two groups → two extract.module dispatches → both produce
    on-disk mutations. Acid-test: Path.read_text() post-apply."""
    target = python_workspace / "lib.rs"
    target.write_text("pub fn add() {}\npub fn sub() {}\n")
    before = target.read_text(encoding="utf-8")

    tool = _make_tool(python_workspace)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _fake_find(file, name_path, project_root):  # noqa: ARG001
        return {
            "start": {"line": 0 if name_path == "add" else 1, "character": 0},
            "end": {"line": 0 if name_path == "add" else 1, "character": 15},
        }

    fake_coord.find_symbol_range = _fake_find

    async def _fake_merge(**_kw):
        return [MagicMock(
            action_id="ra:1", id="ra:1", title="Move to module",
            kind="refactor.extract.module", provenance="rust-analyzer",
            is_preferred=False,
        )]

    fake_coord.merge_code_actions = _fake_merge
    # The applier-wire-through proof: each get_action_edit returns a
    # WorkspaceEdit that puts a `// moved-N` marker at the symbol's line.
    edit_n = {"n": 0}

    def _fake_resolve(_aid):
        edit_n["n"] += 1
        line = 0 if edit_n["n"] == 1 else 1
        return {
            "changes": {
                target.as_uri(): [{
                    "range": {
                        "start": {"line": line, "character": 0},
                        "end": {"line": line, "character": 0},
                    },
                    "newText": f"// moved-{edit_n['n']}\n",
                }],
            },
        }

    fake_coord.get_action_edit = _fake_resolve
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            groups={"helpers": ["add"], "ops": ["sub"]},
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True
    after = target.read_text(encoding="utf-8")
    assert after != before
    # Two mutations landed on disk:
    assert "// moved-1" in after
    assert "// moved-2" in after
