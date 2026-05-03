"""v1.5 G7-A — real-disk acid tests for 10 Rust ergonomic facades.

Spec § Test discipline gaps (lines 157-174). The 21 zero-coverage
facades surveyed by Wave 0 included these 10 Rust-arm ergonomic
tools. Each test below sets up a real ``tmp_path`` workspace, drives
the facade with a mock coordinator that surfaces a single winner
``CodeAction`` whose resolved ``WorkspaceEdit`` contains a known
on-disk mutation, and asserts via ``Path.read_text()`` that the v0.3.0
applier wrote the expected content to disk.

Discipline:
  * one test per facade (10 total).
  * each test sets ``before = src.read_text()`` *before* the call.
  * each test asserts both ``after != before`` and a substring of
    the expected new content.
  * tests skip cleanly on partial dev hosts ONLY when the facade
    requires a Rust toolchain at runtime — these tests deliberately
    DO NOT need rust-analyzer because the coordinator is mocked.
    The pattern proves the facade-applier wire is honest end-to-end
    against any LSP whose actions resolve to a real ``WorkspaceEdit``.

Facades covered (10):
  1. ChangeVisibilityTool
  2. ChangeReturnTypeTool
  3. ConvertModuleLayoutTool
  4. TidyStructureTool
  5. ChangeTypeShapeTool
  6. CompleteMatchArmsTool
  7. ExtractLifetimeTool
  8. ExpandGlobImportsTool
  9. GenerateTraitImplScaffoldTool
  10. GenerateMemberTool

Authored-by: AI Hive®.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    ChangeReturnTypeTool,
    ChangeTypeShapeTool,
    ChangeVisibilityTool,
    CompleteMatchArmsTool,
    ConvertModuleLayoutTool,
    ExpandGlobImportsTool,
    ExtractLifetimeTool,
    GenerateMemberTool,
    GenerateTraitImplScaffoldTool,
    TidyStructureTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Shared fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


_T = TypeVar("_T")


def _make_tool(cls: type[_T], project_root: Path) -> _T:
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[attr-defined]
    return tool


def _action(action_id: str, title: str, kind: str) -> MagicMock:
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.is_preferred = False
    a.provenance = "rust-analyzer"
    a.kind = kind
    return a


def _make_coord(
    *,
    actions: list[Any],
    edit_for: dict[str, dict[str, Any]],
) -> MagicMock:
    """Mock coordinator surfacing ``actions`` and resolving each id from
    ``edit_for`` to a WorkspaceEdit dict."""
    coord = MagicMock()
    coord.supports_kind.return_value = True

    async def _merge(**_kw: Any) -> list[Any]:
        return actions

    coord.merge_code_actions = _merge

    def _resolve(aid: str) -> dict[str, Any] | None:
        return edit_for.get(aid)

    coord.get_action_edit = _resolve
    return coord


def _replace_edit(uri: str, line: int, ch_start: int, ch_end: int, new_text: str) -> dict[str, Any]:
    return {
        "changes": {
            uri: [{
                "range": {
                    "start": {"line": line, "character": ch_start},
                    "end": {"line": line, "character": ch_end},
                },
                "newText": new_text,
            }],
        },
    }


def _insert_edit(uri: str, line: int, ch: int, text: str) -> dict[str, Any]:
    return _replace_edit(uri, line, ch, ch, text)


# ---------------------------------------------------------------------------
# 1. ChangeVisibilityTool
# ---------------------------------------------------------------------------


def test_g7a_change_visibility_real_disk_pub_crate(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("fn helper() {}\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "ra:vis", "Change visibility to pub(crate)",
            "refactor.rewrite.change_visibility",
        )],
        edit_for={"ra:vis": _insert_edit(src.as_uri(), 0, 0, "pub(crate) ")},
    )
    tool = _make_tool(ChangeVisibilityTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 3},
            target_visibility="pub_crate",
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "pub(crate) fn helper()" in after


# ---------------------------------------------------------------------------
# 2. ChangeReturnTypeTool
# ---------------------------------------------------------------------------


def test_g7a_change_return_type_real_disk_to_result(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("pub fn calc() -> i32 { 0 }\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "ra:rt", "Change return type to Result<i32, Error>",
            "refactor.rewrite.change_return_type",
        )],
        edit_for={"ra:rt": _replace_edit(
            src.as_uri(), 0, 17, 20, "Result<i32, Error>",
        )},
    )
    tool = _make_tool(ChangeReturnTypeTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 7},
            new_return_type="Result<i32, Error>",
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "Result<i32, Error>" in after


# ---------------------------------------------------------------------------
# 3. ConvertModuleLayoutTool
# ---------------------------------------------------------------------------


def test_g7a_convert_module_layout_real_disk_inline_to_file(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("mod inner { fn x() {} }\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    # Replace the inline body with a file-backed declaration.
    coord = _make_coord(
        actions=[_action(
            "ra:ml", "Move inline module to file",
            "refactor.rewrite.move_module_to_file",
        )],
        edit_for={"ra:ml": _replace_edit(
            src.as_uri(), 0, 0, len("mod inner { fn x() {} }"), "mod inner;",
        )},
    )
    tool = _make_tool(ConvertModuleLayoutTool, tmp_path)
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
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "mod inner;" in after


# ---------------------------------------------------------------------------
# 4. TidyStructureTool — file scope (uses compute_file_range now)
# ---------------------------------------------------------------------------


def test_g7a_tidy_structure_real_disk_file_scope(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text(
        "struct Foo {\n    b: i32,\n    a: i32,\n}\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    # One action per kind in _TIDY_STRUCTURE_KINDS — all three are
    # supported and dispatched at file scope. Only one returns a
    # mutating edit (reorder_fields swaps `b` and `a`).
    actions = [
        _action(
            "ra:reorder_impl", "Reorder impl items",
            "refactor.rewrite.reorder_impl_items",
        ),
        _action(
            "ra:sort_items", "Sort items",
            "refactor.rewrite.sort_items",
        ),
        _action(
            "ra:reorder_fields", "Reorder fields",
            "refactor.rewrite.reorder_fields",
        ),
    ]
    edit_for = {
        "ra:reorder_fields": {
            "changes": {
                src.as_uri(): [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 4, "character": 0},
                    },
                    "newText": "struct Foo {\n    a: i32,\n    b: i32,\n}\n",
                }],
            },
        },
    }
    coord = _make_coord(actions=actions, edit_for=edit_for)

    tool = _make_tool(TidyStructureTool, tmp_path)
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
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    # `a` comes before `b` post-reorder.
    a_idx = after.index("a: i32")
    b_idx = after.index("b: i32")
    assert a_idx < b_idx, after


# ---------------------------------------------------------------------------
# 5. ChangeTypeShapeTool
# ---------------------------------------------------------------------------


def test_g7a_change_type_shape_real_disk_named_struct(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("struct Foo(i32);\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "ra:ts", "Convert tuple struct to named struct",
            "refactor.rewrite.convert_tuple_struct_to_named_struct",
        )],
        edit_for={"ra:ts": _replace_edit(
            src.as_uri(), 0, 0, len("struct Foo(i32);"),
            "struct Foo { field0: i32 }",
        )},
    )
    tool = _make_tool(ChangeTypeShapeTool, tmp_path)
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
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "field0: i32" in after


# ---------------------------------------------------------------------------
# 6. CompleteMatchArmsTool
# ---------------------------------------------------------------------------


def test_g7a_complete_match_arms_real_disk(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text(
        "enum E { A, B }\nfn f(e: E) {\n    match e {}\n}\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    # The assist inserts the missing arms inside the `{}` block.
    coord = _make_coord(
        actions=[_action(
            "ra:ma", "Add missing match arms",
            "quickfix.add_missing_match_arms",
        )],
        edit_for={"ra:ma": _replace_edit(
            src.as_uri(), 2, 13, 14,
            "\n        E::A => todo!(),\n        E::B => todo!(),\n    ",
        )},
    )
    tool = _make_tool(CompleteMatchArmsTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 2, "character": 10},
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "E::A => todo!()" in after
    assert "E::B => todo!()" in after


# ---------------------------------------------------------------------------
# 7. ExtractLifetimeTool
# ---------------------------------------------------------------------------


def test_g7a_extract_lifetime_real_disk(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("fn f(x: &i32) -> &i32 { x }\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "ra:lt", "Extract into a fresh lifetime 'a",
            "refactor.extract.extract_lifetime",
        )],
        edit_for={"ra:lt": _replace_edit(
            src.as_uri(), 0, 0, len("fn f(x: &i32) -> &i32 { x }"),
            "fn f<'a>(x: &'a i32) -> &'a i32 { x }",
        )},
    )
    tool = _make_tool(ExtractLifetimeTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 8},
            lifetime_name="a",
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "<'a>" in after
    assert "&'a i32" in after


# ---------------------------------------------------------------------------
# 8. ExpandGlobImportsTool
# ---------------------------------------------------------------------------


def test_g7a_expand_glob_imports_real_disk(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("use foo::*;\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "ra:gi", "Expand glob import",
            "refactor.rewrite.expand_glob_imports",
        )],
        edit_for={"ra:gi": _replace_edit(
            src.as_uri(), 0, 0, len("use foo::*;"),
            "use foo::{a, b, c};",
        )},
    )
    tool = _make_tool(ExpandGlobImportsTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 9},
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "use foo::{a, b, c};" in after


# ---------------------------------------------------------------------------
# 9. GenerateTraitImplScaffoldTool
# ---------------------------------------------------------------------------


def test_g7a_generate_trait_impl_scaffold_real_disk(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text("struct Foo;\n", encoding="utf-8")
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "ra:ti", "Implement Display for Foo",
            "refactor.rewrite.generate_trait_impl",
        )],
        edit_for={"ra:ti": _insert_edit(
            src.as_uri(), 1, 0,
            "\nimpl Display for Foo {\n    fn fmt(&self, f: &mut Formatter<'_>) -> Result {\n        todo!()\n    }\n}\n",
        )},
    )
    tool = _make_tool(GenerateTraitImplScaffoldTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 7},
            trait_name="Display",
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "impl Display for Foo" in after


# ---------------------------------------------------------------------------
# 10. GenerateMemberTool — getter
# ---------------------------------------------------------------------------


def test_g7a_generate_member_real_disk_getter(tmp_path: Path) -> None:
    src = tmp_path / "lib.rs"
    src.write_text(
        "struct Foo { name: String }\nimpl Foo {}\n",
        encoding="utf-8",
    )
    before = src.read_text(encoding="utf-8")

    coord = _make_coord(
        actions=[_action(
            "ra:gm", "Generate a getter method",
            "refactor.rewrite.generate_getter",
        )],
        edit_for={"ra:gm": _replace_edit(
            src.as_uri(), 1, 10, 11,
            "\n    pub fn name(&self) -> &String {\n        &self.name\n    }\n",
        )},
    )
    tool = _make_tool(GenerateMemberTool, tmp_path)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 13},
            member_kind="getter",
            language="rust",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    after = src.read_text(encoding="utf-8")
    assert after != before
    assert "pub fn name(&self) -> &String" in after
