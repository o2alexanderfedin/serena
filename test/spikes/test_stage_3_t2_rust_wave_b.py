"""Stage 3 T2 — Rust ergonomic facades wave B.

Per scope-report §4.2:
- ScalpelChangeReturnTypeTool (row H tail) — function return-type rewriter.
- ScalpelCompleteMatchArmsTool (row I) — ``add_missing_match_arms``.
- ScalpelExtractLifetimeTool (row H) — lifetime-introduction assist.
- ScalpelExpandGlobImportsTool (row D) — ``expand_glob_imports``.

Same dispatch pattern as Wave A: workspace_boundary_guard,
``coordinator_for_facade``, ``merge_code_actions(only=[<kind>])``, with
RefactorResult applied/dry_run/SYMBOL_NOT_FOUND branches.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.facade_support import get_apply_source
from serena.tools.scalpel_facades import (
    ScalpelChangeReturnTypeTool,
    ScalpelCompleteMatchArmsTool,
    ScalpelExpandGlobImportsTool,
    ScalpelExtractLifetimeTool,
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


def _fake_action(kind: str):
    return MagicMock(action_id=f"ra:{kind}", title="x", kind=kind, provenance="rust-analyzer")


def _fake_coord_with(kind: str | None):
    coord = MagicMock()

    async def _merge(**kwargs):
        only = list(kwargs.get("only", []))
        if kind is None or kind not in only:
            return []
        return [_fake_action(kind)]
    coord.merge_code_actions = _merge
    return coord


def _exercise_dispatch(cls, kwargs: dict, kind: str | None, tmp_path: Path) -> dict:
    src = tmp_path / "lib.rs"
    src.write_text("fn x() -> i32 { 0 }\n")
    tool = _make_tool(cls, tmp_path)
    coord = _fake_coord_with(kind)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(file=str(src), language="rust", **kwargs)
    return json.loads(out)


# ---------- ScalpelChangeReturnTypeTool ------------------------------------


def test_change_return_type_dispatches(tmp_path: Path):
    payload = _exercise_dispatch(
        ScalpelChangeReturnTypeTool,
        kwargs={"position": {"line": 0, "character": 6}, "new_return_type": "u64"},
        kind="refactor.rewrite.change_return_type",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_change_return_type_no_action(tmp_path: Path):
    payload = _exercise_dispatch(
        ScalpelChangeReturnTypeTool,
        kwargs={"position": {"line": 0, "character": 0}, "new_return_type": "u64"},
        kind=None,
        tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


def test_change_return_type_dry_run(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("fn x() -> i32 { 0 }\n")
    tool = _make_tool(ScalpelChangeReturnTypeTool, tmp_path)
    coord = _fake_coord_with("refactor.rewrite.change_return_type")
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 6},
            new_return_type="u64", language="rust", dry_run=True,
        )
    payload = json.loads(out)
    assert payload["preview_token"] is not None


# ---------- ScalpelCompleteMatchArmsTool -----------------------------------


def test_complete_match_arms_dispatches(tmp_path: Path):
    payload = _exercise_dispatch(
        ScalpelCompleteMatchArmsTool,
        kwargs={"position": {"line": 0, "character": 0}},
        kind="quickfix.add_missing_match_arms",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_complete_match_arms_no_action(tmp_path: Path):
    payload = _exercise_dispatch(
        ScalpelCompleteMatchArmsTool,
        kwargs={"position": {"line": 0, "character": 0}},
        kind=None,
        tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- ScalpelExtractLifetimeTool -------------------------------------


def test_extract_lifetime_dispatches(tmp_path: Path):
    payload = _exercise_dispatch(
        ScalpelExtractLifetimeTool,
        kwargs={"position": {"line": 0, "character": 0}, "lifetime_name": "a"},
        kind="refactor.extract.extract_lifetime",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_extract_lifetime_no_action(tmp_path: Path):
    payload = _exercise_dispatch(
        ScalpelExtractLifetimeTool,
        kwargs={"position": {"line": 0, "character": 0}, "lifetime_name": "a"},
        kind=None,
        tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- ScalpelExpandGlobImportsTool -----------------------------------


def test_expand_glob_imports_dispatches(tmp_path: Path):
    payload = _exercise_dispatch(
        ScalpelExpandGlobImportsTool,
        kwargs={"position": {"line": 0, "character": 0}},
        kind="refactor.rewrite.expand_glob_imports",
        tmp_path=tmp_path,
    )
    assert payload["applied"] is True


def test_expand_glob_imports_no_action(tmp_path: Path):
    payload = _exercise_dispatch(
        ScalpelExpandGlobImportsTool,
        kwargs={"position": {"line": 0, "character": 0}},
        kind=None,
        tmp_path=tmp_path,
    )
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- Re-export + boundary sanity ------------------------------------


def test_all_four_tools_reexported_from_serena_tools():
    import serena.tools as tools_module
    for name in (
        "ScalpelChangeReturnTypeTool",
        "ScalpelCompleteMatchArmsTool",
        "ScalpelExtractLifetimeTool",
        "ScalpelExpandGlobImportsTool",
    ):
        assert hasattr(tools_module, name)


def test_apply_methods_invoke_workspace_boundary_guard():
    for cls in (
        ScalpelChangeReturnTypeTool,
        ScalpelCompleteMatchArmsTool,
        ScalpelExtractLifetimeTool,
        ScalpelExpandGlobImportsTool,
    ):
        src = get_apply_source(cls)
        assert "workspace_boundary_guard(" in src, (
            f"{cls.__name__}.apply must call workspace_boundary_guard()"
        )


def test_tool_names_match_scope_report_naming():
    expected = {
        ScalpelChangeReturnTypeTool: "scalpel_change_return_type",
        ScalpelCompleteMatchArmsTool: "scalpel_complete_match_arms",
        ScalpelExtractLifetimeTool: "scalpel_extract_lifetime",
        ScalpelExpandGlobImportsTool: "scalpel_expand_glob_imports",
    }
    for cls, name in expected.items():
        assert cls.get_name_from_cls() == name


def test_workspace_boundary_blocks_outside_root(tmp_path: Path):
    tool = _make_tool(ScalpelChangeReturnTypeTool, tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.rs"),
        position={"line": 0, "character": 0},
        new_return_type="u64", language="rust",
    )
    assert json.loads(out)["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
