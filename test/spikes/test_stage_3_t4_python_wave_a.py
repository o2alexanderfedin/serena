"""Stage 3 T4 — Python ergonomic facades wave A (pylsp-rope-backed).

Per scope-report §4.4.1:
- ConvertToMethodObjectTool (row 5) — method_to_method_object.
- LocalToFieldTool (row 4) — local_to_field.
- UseFunctionTool (row 6) — use_function.
- IntroduceParameterTool (row 7) — introduce_parameter.

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
    ConvertToMethodObjectTool,
    IntroduceParameterTool,
    LocalToFieldTool,
    UseFunctionTool,
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


# ---------- ConvertToMethodObjectTool -------------------------------


def test_convert_to_method_object_dispatches(tmp_path: Path):
    payload = _exercise(
        ConvertToMethodObjectTool,
        kwargs={"position": {"line": 1, "character": 8}},
        kind="refactor.rewrite.method_to_method_object",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_convert_to_method_object_no_action(tmp_path: Path):
    payload = _exercise(
        ConvertToMethodObjectTool,
        kwargs={"position": {"line": 0, "character": 0}},
        kind=None, tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- LocalToFieldTool ----------------------------------------


def test_local_to_field_dispatches(tmp_path: Path):
    payload = _exercise(
        LocalToFieldTool,
        kwargs={"position": {"line": 1, "character": 4}},
        kind="refactor.rewrite.local_to_field",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_local_to_field_dry_run(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("\n")
    tool = _make_tool(LocalToFieldTool, tmp_path)
    coord = _fake_coord("refactor.rewrite.local_to_field")
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            language="python", dry_run=True,
        )
    payload = json.loads(out)
    assert payload["preview_token"] is not None


# ---------- UseFunctionTool -----------------------------------------


def test_use_function_dispatches(tmp_path: Path):
    payload = _exercise(
        UseFunctionTool,
        kwargs={"position": {"line": 0, "character": 4}},
        kind="refactor.rewrite.use_function",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_use_function_no_action(tmp_path: Path):
    payload = _exercise(
        UseFunctionTool,
        kwargs={"position": {"line": 0, "character": 0}},
        kind=None, tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- IntroduceParameterTool ----------------------------------


def test_introduce_parameter_dispatches(tmp_path: Path):
    payload = _exercise(
        IntroduceParameterTool,
        kwargs={"position": {"line": 1, "character": 8}, "parameter_name": "p"},
        kind="refactor.rewrite.introduce_parameter",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_introduce_parameter_no_action(tmp_path: Path):
    payload = _exercise(
        IntroduceParameterTool,
        kwargs={"position": {"line": 0, "character": 0}, "parameter_name": "p"},
        kind=None, tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- Re-export + boundary sanity ------------------------------------


def test_all_four_tools_reexported_from_serena_tools():
    import serena.tools as tools_module
    for name in (
        "ConvertToMethodObjectTool",
        "LocalToFieldTool",
        "UseFunctionTool",
        "IntroduceParameterTool",
    ):
        assert hasattr(tools_module, name)


def test_apply_methods_invoke_workspace_boundary_guard():
    for cls in (
        ConvertToMethodObjectTool,
        LocalToFieldTool,
        UseFunctionTool,
        IntroduceParameterTool,
    ):
        src = get_apply_source(cls)
        assert "workspace_boundary_guard(" in src, (
            f"{cls.__name__}.apply must call workspace_boundary_guard()"
        )


def test_tool_names_match_scope_report_naming():
    expected = {
        ConvertToMethodObjectTool: "convert_to_method_object",
        LocalToFieldTool: "local_to_field",
        UseFunctionTool: "use_function",
        IntroduceParameterTool: "introduce_parameter",
    }
    for cls, name in expected.items():
        assert cls.get_name_from_cls() == name


def test_workspace_boundary_blocks(tmp_path: Path):
    tool = _make_tool(LocalToFieldTool, tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.py"),
        position={"line": 0, "character": 0}, language="python",
    )
    assert json.loads(out)["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


# ---------------------------------------------------------------------------
# v1.5 G7-C — sibling real-disk acid test.
#
# The mock-only tests above assert dispatch shape only. This sibling
# extends the discipline: tmp_path workspace + mock coord whose
# resolved WorkspaceEdit lands actual content on disk.
# ---------------------------------------------------------------------------


def test_local_to_field_real_disk_lands_self_field_on_disk(tmp_path: Path):
    """Acid-test sibling: local_to_field rewrite; assert the post-apply
    file has the local promoted to ``self.x``."""
    src = tmp_path / "module.py"
    src.write_text(
        "class C:\n    def m(self):\n        x = 1\n        return x\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")
    tool = _make_tool(LocalToFieldTool, tmp_path)

    coord = MagicMock()
    coord.supports_kind.return_value = True

    async def _merge(**_kw):
        return [MagicMock(
            action_id="rope:l2f", id="rope:l2f", title="local to field",
            kind="refactor.rewrite.local_to_field",
            provenance="pylsp-rope", is_preferred=False,
        )]

    coord.merge_code_actions = _merge
    coord.get_action_edit = lambda _aid: {
        "changes": {
            src.as_uri(): [{
                "range": {
                    "start": {"line": 2, "character": 8},
                    "end": {"line": 3, "character": 16},
                },
                "newText": "self.x = 1\n        return self.x",
            }],
        },
    }
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 2, "character": 8},
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "self.x = 1" in after
    assert "return self.x" in after
