"""Stage 3 T1 — Rust ergonomic facades wave A.

Per scope-report §4.2:
- ScalpelConvertModuleLayoutTool (row B.1) — convert ``mod foo;`` <-> ``mod foo { ... }``.
- ScalpelChangeVisibilityTool (row E) — toggle pub/pub(crate)/pub(super)/private.
- ScalpelTidyStructureTool (row F composite) — reorder_impl_items + sort_items + reorder_fields.
- ScalpelChangeTypeShapeTool (row H composite) — ``convert_*_to_*`` family.

Each facade follows the Stage 2A dispatch pattern: workspace_boundary_guard,
``coordinator_for_facade``, ``merge_code_actions(only=[<kind>])``, return
``RefactorResult`` with applied/dry_run/SYMBOL_NOT_FOUND branches.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.facade_support import get_apply_source
from serena.tools.scalpel_facades import (
    ScalpelChangeTypeShapeTool,
    ScalpelChangeVisibilityTool,
    ScalpelConvertModuleLayoutTool,
    ScalpelTidyStructureTool,
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


def _fake_action(kind: str, title: str = "fake-assist", provenance: str = "rust-analyzer"):
    return MagicMock(
        action_id=f"ra:{kind}",
        title=title,
        kind=kind,
        provenance=provenance,
    )


def _fake_coord(actions_by_only: dict[str, list]):
    """Return a fake coordinator whose merge_code_actions matches ``only=[kind]``."""
    coord = MagicMock()

    async def _merge(**kwargs):
        only = kwargs.get("only", [])
        out: list = []
        for kind in only:
            out.extend(actions_by_only.get(kind, []))
        return out
    coord.merge_code_actions = _merge
    return coord


# ---------- ScalpelConvertModuleLayoutTool ---------------------------------


def test_convert_module_layout_dispatches_to_inline_kind(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("mod foo;\n")
    tool = _make_tool(ScalpelConvertModuleLayoutTool, tmp_path)
    coord = _fake_coord({
        "refactor.rewrite.move_module_to_file": [_fake_action(
            "refactor.rewrite.move_module_to_file"
        )],
    })
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 4},
            target_layout="file",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["checkpoint_id"]


def test_convert_module_layout_no_action_returns_symbol_not_found(
    tmp_path: Path,
):
    src = tmp_path / "lib.rs"
    src.write_text("// no module here\n")
    tool = _make_tool(ScalpelConvertModuleLayoutTool, tmp_path)
    coord = _fake_coord({})
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            target_layout="inline",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


def test_convert_module_layout_dry_run_yields_preview_token(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("mod foo;\n")
    tool = _make_tool(ScalpelConvertModuleLayoutTool, tmp_path)
    coord = _fake_coord({
        "refactor.rewrite.move_module_to_file": [_fake_action(
            "refactor.rewrite.move_module_to_file"
        )],
    })
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 4},
            target_layout="file",
            language="rust",
            dry_run=True,
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"] is not None


def test_convert_module_layout_workspace_boundary_blocked(tmp_path: Path):
    tool = _make_tool(ScalpelConvertModuleLayoutTool, tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.rs"),
        position={"line": 0, "character": 0},
        target_layout="file",
        language="rust",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


# ---------- ScalpelChangeVisibilityTool ------------------------------------


def test_change_visibility_dispatches(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("fn private_fn() {}\n")
    tool = _make_tool(ScalpelChangeVisibilityTool, tmp_path)
    coord = _fake_coord({
        "refactor.rewrite.change_visibility": [_fake_action(
            "refactor.rewrite.change_visibility", title="Make pub"
        )],
    })
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 3},
            target_visibility="pub",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["checkpoint_id"]


def test_change_visibility_no_action_returns_symbol_not_found(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("// nothing\n")
    tool = _make_tool(ScalpelChangeVisibilityTool, tmp_path)
    coord = _fake_coord({})
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            target_visibility="pub_crate",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


def test_change_visibility_dry_run(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("fn x() {}\n")
    tool = _make_tool(ScalpelChangeVisibilityTool, tmp_path)
    coord = _fake_coord({
        "refactor.rewrite.change_visibility": [_fake_action(
            "refactor.rewrite.change_visibility"
        )],
    })
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 3},
            target_visibility="pub",
            language="rust",
            dry_run=True,
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"] is not None


# ---------- ScalpelTidyStructureTool ---------------------------------------


def test_tidy_structure_calls_three_kinds_when_scope_file(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("struct S { b: i32, a: i32 }\n")
    tool = _make_tool(ScalpelTidyStructureTool, tmp_path)
    seen: list[list[str]] = []
    coord = MagicMock()

    async def _merge(**kwargs):
        seen.append(list(kwargs["only"]))
        return [_fake_action(kwargs["only"][0])]
    coord.merge_code_actions = _merge
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            scope="file",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    seen_kinds = {only[0] for only in seen}
    assert "refactor.rewrite.reorder_impl_items" in seen_kinds
    assert "refactor.rewrite.sort_items" in seen_kinds
    assert "refactor.rewrite.reorder_fields" in seen_kinds


def test_tidy_structure_no_actions_returns_no_op(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("// empty\n")
    tool = _make_tool(ScalpelTidyStructureTool, tmp_path)
    coord = _fake_coord({})
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(file=str(src), scope="file", language="rust")
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["no_op"] is True


def test_tidy_structure_dry_run(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("struct S { b: i32, a: i32 }\n")
    tool = _make_tool(ScalpelTidyStructureTool, tmp_path)
    coord = _fake_coord({
        "refactor.rewrite.reorder_fields": [_fake_action(
            "refactor.rewrite.reorder_fields"
        )],
    })
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src), scope="file", language="rust", dry_run=True,
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["preview_token"] is not None


# ---------- ScalpelChangeTypeShapeTool -------------------------------------


def test_change_type_shape_dispatches(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("struct S(i32);\n")
    tool = _make_tool(ScalpelChangeTypeShapeTool, tmp_path)
    coord = _fake_coord({
        "refactor.rewrite.convert_tuple_struct_to_named_struct": [_fake_action(
            "refactor.rewrite.convert_tuple_struct_to_named_struct"
        )],
    })
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 7},
            target_shape="named_struct",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_change_type_shape_unknown_target_returns_invalid_argument(
    tmp_path: Path,
):
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(ScalpelChangeTypeShapeTool, tmp_path)
    out = tool.apply(
        file=str(src),
        position={"line": 0, "character": 0},
        target_shape="bogus",
        language="rust",
    )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_change_type_shape_no_action_returns_symbol_not_found(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(ScalpelChangeTypeShapeTool, tmp_path)
    coord = _fake_coord({})
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            target_shape="named_struct",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- Re-export sanity ------------------------------------------------


def test_all_four_tools_reexported_from_serena_tools():
    import serena.tools as tools_module
    for name in (
        "ScalpelConvertModuleLayoutTool",
        "ScalpelChangeVisibilityTool",
        "ScalpelTidyStructureTool",
        "ScalpelChangeTypeShapeTool",
    ):
        assert hasattr(tools_module, name)


def test_apply_methods_invoke_workspace_boundary_guard():
    """v0.2.0-Stage3 — every new facade must call workspace_boundary_guard."""
    for cls in (
        ScalpelConvertModuleLayoutTool,
        ScalpelChangeVisibilityTool,
        ScalpelTidyStructureTool,
        ScalpelChangeTypeShapeTool,
    ):
        src = get_apply_source(cls)
        assert "workspace_boundary_guard(" in src, (
            f"{cls.__name__}.apply must call workspace_boundary_guard()"
        )


def test_tool_names_match_scope_report_naming():
    expected = {
        ScalpelConvertModuleLayoutTool: "scalpel_convert_module_layout",
        ScalpelChangeVisibilityTool: "scalpel_change_visibility",
        ScalpelTidyStructureTool: "scalpel_tidy_structure",
        ScalpelChangeTypeShapeTool: "scalpel_change_type_shape",
    }
    for cls, name in expected.items():
        assert cls.get_name_from_cls() == name
