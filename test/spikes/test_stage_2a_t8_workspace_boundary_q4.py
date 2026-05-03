"""Stage 2A T9 — Q4 workspace-boundary integration tests across 6 facades."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    ExtractTool,
    ImportsOrganizeTool,
    InlineTool,
    RenameTool,
    SplitFileTool,
    TransactionCommitTool,  # noqa: F401 — imported for completeness
)
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def fake_coord_always_succeeds():
    fake = MagicMock()

    async def _merge(**kwargs):
        return [MagicMock(action_id="ok", title="ok", kind=kwargs["only"][0],
                          provenance="rust-analyzer")]
    fake.merge_code_actions = _merge

    async def _find_pos(**kwargs):  # noqa: ARG001
        return {"line": 0, "character": 0}
    fake.find_symbol_position = _find_pos

    async def _merge_rename(relative_file_path, line, column, new_name, language="python"):
        del relative_file_path, line, column, new_name, language
        return ({"changes": {}}, [])
    fake.merge_rename = _merge_rename
    return fake


def _make(cls, project_root):
    t = cls.__new__(cls)
    t.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return t


@pytest.mark.parametrize("cls,kwargs", [
    (ExtractTool, dict(target="function",
                              range={"start": {"line": 0, "character": 0},
                                     "end": {"line": 0, "character": 1}},
                              language="python")),
    (InlineTool, dict(target="call",
                             position={"line": 0, "character": 0},
                             scope="single_call_site",
                             language="python")),
    (RenameTool, dict(name_path="x", new_name="y", language="python")),
    (ImportsOrganizeTool, dict(language="python")),
    (SplitFileTool, dict(groups={"a": ["x"]}, language="python")),
])
def test_wb2_out_of_workspace_rejected(cls, kwargs, tmp_path):
    tool = _make(cls, tmp_path)
    outside = tmp_path.parent / "elsewhere.py"
    if cls is ImportsOrganizeTool:
        out = tool.apply(files=[str(outside)], **kwargs)
    else:
        out = tool.apply(file=str(outside), **kwargs)
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    assert payload["failure"]["recoverable"] is False


@pytest.mark.parametrize("cls,kwargs", [
    (ExtractTool, dict(target="function",
                              range={"start": {"line": 0, "character": 0},
                                     "end": {"line": 0, "character": 1}},
                              language="python")),
    (InlineTool, dict(target="call",
                             position={"line": 0, "character": 0},
                             scope="single_call_site",
                             language="python")),
    (ImportsOrganizeTool, dict(language="python")),
])
def test_wb3_extra_paths_opt_in_allows_out_of_workspace(
    cls, kwargs, tmp_path, monkeypatch, fake_coord_always_succeeds,
):
    extra = tmp_path.parent / "extra-root"
    extra.mkdir(exist_ok=True)
    target = extra / "f.py"
    target.write_text("x = 1\n")
    monkeypatch.setenv("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", str(extra))
    tool = _make(cls, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord_always_succeeds,
    ):
        if cls is ImportsOrganizeTool:
            out = tool.apply(files=[str(target)], **kwargs)
        else:
            out = tool.apply(file=str(target), **kwargs)
    payload = json.loads(out)
    assert payload.get("failure") is None or \
        payload["failure"]["code"] != "WORKSPACE_BOUNDARY_VIOLATION"


@pytest.mark.parametrize("cls,kwargs", [
    (ExtractTool, dict(target="function",
                              range={"start": {"line": 0, "character": 0},
                                     "end": {"line": 0, "character": 1}},
                              language="python")),
    (InlineTool, dict(target="call",
                             position={"line": 0, "character": 0},
                             scope="single_call_site",
                             language="python")),
])
def test_wb4_allow_out_of_workspace_override(
    cls, kwargs, tmp_path, fake_coord_always_succeeds,
):
    outside = tmp_path.parent / "elsewhere.py"
    outside.write_text("x = 1\n")
    tool = _make(cls, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord_always_succeeds,
    ):
        out = tool.apply(file=str(outside), allow_out_of_workspace=True, **kwargs)
    payload = json.loads(out)
    assert payload.get("failure") is None or \
        payload["failure"]["code"] != "WORKSPACE_BOUNDARY_VIOLATION"


def test_wb5_symlink_through_workspace_to_outside_rejected(tmp_path):
    outside = tmp_path.parent / "real-elsewhere.py"
    outside.write_text("x = 1\n")
    link = tmp_path / "link.py"
    link.symlink_to(outside)
    tool = _make(ExtractTool, tmp_path)
    out = tool.apply(
        file=str(link),
        range={"start": {"line": 0, "character": 0},
               "end": {"line": 0, "character": 1}},
        target="function", language="python",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


def test_wb6_dotdot_path_resolves_outside_and_rejected(tmp_path):
    outside = tmp_path.parent / "outside.py"
    outside.write_text("x = 1\n")
    sneaky = tmp_path / ".." / "outside.py"
    tool = _make(ExtractTool, tmp_path)
    out = tool.apply(
        file=str(sneaky),
        range={"start": {"line": 0, "character": 0},
               "end": {"line": 0, "character": 1}},
        target="function", language="python",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
