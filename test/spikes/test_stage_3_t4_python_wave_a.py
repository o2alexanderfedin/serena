"""Stage 3 T4 — Python ergonomic facades wave A (pylsp-rope-backed).

Per scope-report §4.4.1:
- ScalpelConvertToMethodObjectTool (row 5) — method_to_method_object.
- ScalpelLocalToFieldTool (row 4) — local_to_field.
- ScalpelUseFunctionTool (row 6) — use_function.
- ScalpelIntroduceParameterTool (row 7) — introduce_parameter.

Each facade dispatches via ``merge_code_actions(only=[<kind>])`` against
the pylsp-rope action surface; tests use the same fake-coord pattern
as Stage 3 Rust waves.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.facade_support import get_apply_source
from serena.tools.scalpel_facades import (
    ScalpelConvertToMethodObjectTool,
    ScalpelIntroduceParameterTool,
    ScalpelLocalToFieldTool,
    ScalpelUseFunctionTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(cls, project_root: Path):
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _fake_coord(kind: str | None):
    coord = MagicMock()

    async def _merge(**kwargs):
        only = list(kwargs.get("only", []))
        if kind is None or kind not in only:
            return []
        return [MagicMock(action_id=f"rope:{kind}", title="x", kind=kind, provenance="pylsp-rope")]
    coord.merge_code_actions = _merge
    return coord


def _exercise(cls, kwargs: dict, kind: str | None, tmp_path: Path) -> dict:
    src = tmp_path / "module.py"
    src.write_text("class C:\n    def m(self): ...\n")
    tool = _make_tool(cls, tmp_path)
    coord = _fake_coord(kind)
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(file=str(src), language="python", **kwargs)
    return json.loads(out)


# ---------- ScalpelConvertToMethodObjectTool -------------------------------


def test_convert_to_method_object_dispatches(tmp_path: Path):
    payload = _exercise(
        ScalpelConvertToMethodObjectTool,
        kwargs={"position": {"line": 1, "character": 8}},
        kind="refactor.rewrite.method_to_method_object",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_convert_to_method_object_no_action(tmp_path: Path):
    payload = _exercise(
        ScalpelConvertToMethodObjectTool,
        kwargs={"position": {"line": 0, "character": 0}},
        kind=None, tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- ScalpelLocalToFieldTool ----------------------------------------


def test_local_to_field_dispatches(tmp_path: Path):
    payload = _exercise(
        ScalpelLocalToFieldTool,
        kwargs={"position": {"line": 1, "character": 4}},
        kind="refactor.rewrite.local_to_field",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_local_to_field_dry_run(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("\n")
    tool = _make_tool(ScalpelLocalToFieldTool, tmp_path)
    coord = _fake_coord("refactor.rewrite.local_to_field")
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            language="python", dry_run=True,
        )
    payload = json.loads(out)
    assert payload["preview_token"] is not None


# ---------- ScalpelUseFunctionTool -----------------------------------------


def test_use_function_dispatches(tmp_path: Path):
    payload = _exercise(
        ScalpelUseFunctionTool,
        kwargs={"position": {"line": 0, "character": 4}},
        kind="refactor.rewrite.use_function",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_use_function_no_action(tmp_path: Path):
    payload = _exercise(
        ScalpelUseFunctionTool,
        kwargs={"position": {"line": 0, "character": 0}},
        kind=None, tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- ScalpelIntroduceParameterTool ----------------------------------


def test_introduce_parameter_dispatches(tmp_path: Path):
    payload = _exercise(
        ScalpelIntroduceParameterTool,
        kwargs={"position": {"line": 1, "character": 8}, "parameter_name": "p"},
        kind="refactor.rewrite.introduce_parameter",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_introduce_parameter_no_action(tmp_path: Path):
    payload = _exercise(
        ScalpelIntroduceParameterTool,
        kwargs={"position": {"line": 0, "character": 0}, "parameter_name": "p"},
        kind=None, tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- Re-export + boundary sanity ------------------------------------


def test_all_four_tools_reexported_from_serena_tools():
    import serena.tools as tools_module
    for name in (
        "ScalpelConvertToMethodObjectTool",
        "ScalpelLocalToFieldTool",
        "ScalpelUseFunctionTool",
        "ScalpelIntroduceParameterTool",
    ):
        assert hasattr(tools_module, name)


def test_apply_methods_invoke_workspace_boundary_guard():
    for cls in (
        ScalpelConvertToMethodObjectTool,
        ScalpelLocalToFieldTool,
        ScalpelUseFunctionTool,
        ScalpelIntroduceParameterTool,
    ):
        src = get_apply_source(cls)
        assert "workspace_boundary_guard(" in src, (
            f"{cls.__name__}.apply must call workspace_boundary_guard()"
        )


def test_tool_names_match_scope_report_naming():
    expected = {
        ScalpelConvertToMethodObjectTool: "scalpel_convert_to_method_object",
        ScalpelLocalToFieldTool: "scalpel_local_to_field",
        ScalpelUseFunctionTool: "scalpel_use_function",
        ScalpelIntroduceParameterTool: "scalpel_introduce_parameter",
    }
    for cls, name in expected.items():
        assert cls.get_name_from_cls() == name


def test_workspace_boundary_blocks(tmp_path: Path):
    tool = _make_tool(ScalpelLocalToFieldTool, tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.py"),
        position={"line": 0, "character": 0}, language="python",
    )
    assert json.loads(out)["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
