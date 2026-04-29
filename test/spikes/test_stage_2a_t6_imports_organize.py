"""Stage 2A T7 — ScalpelImportsOrganizeTool tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ScalpelImportsOrganizeTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(project_root: Path) -> ScalpelImportsOrganizeTool:
    tool = ScalpelImportsOrganizeTool.__new__(ScalpelImportsOrganizeTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def test_organize_imports_multi_file_python(tmp_path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    for f in (f1, f2):
        f.write_text("import os, sys\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True
    call_count = {"n": 0}
    only_seen: list[str] = []

    async def _merge(**kwargs):
        call_count["n"] += 1
        # v1.5 G4-9: imports_organize now dispatches one of three sub-kinds
        # per (file, flag) pair instead of the unified umbrella kind.
        only = kwargs.get("only") or []
        only_seen.append(only[0] if only else "")
        return [MagicMock(action_id=f"ruff:{call_count['n']}",
                          title="organize", kind=only[0] if only else "",
                          provenance="ruff")]
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            files=[str(f1), str(f2)], language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    # 2 files × 3 default-True flags = 6 dispatches. Verify each sub-kind
    # was issued at least once (per-file × per-kind product).
    assert call_count["n"] == 6, only_seen
    assert any("removeUnused" in k for k in only_seen), only_seen
    assert any("sortImports" in k for k in only_seen), only_seen
    assert any("quickfix.import" in k for k in only_seen), only_seen


def test_organize_imports_no_actions_is_no_op(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import sys\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):  # noqa: ARG001
        return []
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(files=[str(f)], language="python")
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["no_op"] is True


def test_organize_imports_engine_filter_logged(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import sys\n")
    tool = _make_tool(tmp_path)
    fake_coord = MagicMock()

    async def _merge(**kwargs):  # noqa: ARG001
        return [
            MagicMock(action_id="ruff:1", title="o", kind="source.organizeImports",
                      provenance="ruff"),
            MagicMock(action_id="bp:1", title="o", kind="source.organizeImports",
                      provenance="basedpyright"),
        ]
    fake_coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            files=[str(f)], engine="ruff", language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    # warnings should mention discarded servers (provenance != ruff)
    assert any("basedpyright" in w for w in payload["warnings"])


def test_organize_imports_workspace_boundary_blocked(tmp_path):
    tool = _make_tool(tmp_path)
    out = tool.apply(
        files=[str(tmp_path.parent / "elsewhere.py")], language="python",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


def test_organize_imports_empty_files_list_is_no_op(tmp_path):
    tool = _make_tool(tmp_path)
    out = tool.apply(files=[], language="python")
    payload = json.loads(out)
    assert payload["no_op"] is True
