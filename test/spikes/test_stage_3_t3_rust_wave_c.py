"""Stage 3 T3 — Rust ergonomic facades wave C.

Per scope-report §4.2:
- GenerateTraitImplScaffoldTool (row G) — ``generate_trait_impl``.
- GenerateMemberTool (row G tail) — generate getter/setter/method stubs.
- ExpandMacroTool (§4.3 row 30; primitive at MVP) — first-class facade
  over rust-analyzer's ``expandMacro`` extension.
- VerifyAfterRefactorTool (§4.7 #7) — composite of runnables +
  relatedTests + runFlycheck. Returns a structured verification report.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any, TypeVar, cast
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.facade_support import get_apply_source
from serena.tools.scalpel_facades import (
    ExpandMacroTool,
    GenerateMemberTool,
    GenerateTraitImplScaffoldTool,
    VerifyAfterRefactorTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


_T = TypeVar("_T")


@pytest.fixture(autouse=True)
def reset_runtime() -> Generator[None, None, None]:
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(cls: type[_T], project_root: Path) -> Any:
    """Construct a tool instance bypassing __init__; returns Any so each call site
    can use the subclass-specific apply() signature without type unification across
    the imported tool union."""
    tool = cls.__new__(cls)
    cast(Any, tool).get_project_root = lambda: str(project_root)
    return tool


def _fake_action(kind: str):
    return MagicMock(action_id=f"ra:{kind}", title="x", kind=kind, provenance="rust-analyzer")


def _fake_coord(actions_by_kind: dict[str, list]):
    coord = MagicMock()

    async def _merge(**kwargs):
        only = list(kwargs.get("only", []))
        out: list = []
        for kind in only:
            out.extend(actions_by_kind.get(kind, []))
        return out
    coord.merge_code_actions = _merge
    return coord


# ---------- GenerateTraitImplScaffoldTool ---------------------------


def test_generate_trait_impl_scaffold_dispatches(tmp_path: Path):
    # v1.5 G4-3 — caller's trait_name now flows into the shared dispatcher's
    # title_match; use trait_name="x" so the substring match succeeds against
    # the default fake_action title "x".
    src = tmp_path / "lib.rs"
    src.write_text("struct S;\n")
    tool = _make_tool(GenerateTraitImplScaffoldTool, tmp_path)
    coord = _fake_coord({
        "refactor.rewrite.generate_trait_impl": [_fake_action(
            "refactor.rewrite.generate_trait_impl"
        )],
    })
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 7},
            trait_name="x", language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_generate_trait_impl_scaffold_no_action(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(GenerateTraitImplScaffoldTool, tmp_path)
    coord = _fake_coord({})
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            trait_name="x", language="rust",
        )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- GenerateMemberTool --------------------------------------


def test_generate_member_dispatches_for_getter(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("struct S { x: i32 }\n")
    tool = _make_tool(GenerateMemberTool, tmp_path)
    coord = _fake_coord({
        "refactor.rewrite.generate_getter": [_fake_action(
            "refactor.rewrite.generate_getter"
        )],
    })
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 11},
            member_kind="getter", language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_generate_member_unknown_kind_returns_invalid_argument(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(GenerateMemberTool, tmp_path)
    out = tool.apply(
        file=str(src), position={"line": 0, "character": 0},
        member_kind="bogus", language="rust",
    )
    assert json.loads(out)["failure"]["code"] == "INVALID_ARGUMENT"


def test_generate_member_no_action(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(GenerateMemberTool, tmp_path)
    coord = _fake_coord({})
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            member_kind="setter", language="rust",
        )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- ExpandMacroTool -----------------------------------------


def test_expand_macro_returns_expanded_text(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text('println!("hi");\n')
    tool = _make_tool(ExpandMacroTool, tmp_path)
    coord = MagicMock()

    async def _expand(**kwargs):
        del kwargs
        return {"name": "println", "expansion": '{ ::std::println!("hi"); }'}
    coord.expand_macro = _expand
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 7},
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["language_findings"]
    finding = payload["language_findings"][0]
    assert finding["code"] == "macro_expansion"
    assert "println" in finding["message"]


def test_expand_macro_returns_no_op_when_coord_returns_none(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("// no macro\n")
    tool = _make_tool(ExpandMacroTool, tmp_path)
    coord = MagicMock()

    async def _expand(**kwargs):
        del kwargs
        return None
    coord.expand_macro = _expand
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["no_op"] is True


# ---------- VerifyAfterRefactorTool ---------------------------------


def test_verify_after_refactor_aggregates_runnables_and_flycheck(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("\n")
    tool = _make_tool(VerifyAfterRefactorTool, tmp_path)
    coord = MagicMock()

    async def _runnables(**kwargs):
        del kwargs
        return [
            {"label": "test mod::a", "kind": "test"},
            {"label": "test mod::b", "kind": "test"},
        ]
    coord.fetch_runnables = _runnables

    async def _flycheck(**kwargs):
        del kwargs
        return {"diagnostics": []}
    coord.run_flycheck = _flycheck
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(file=str(src), language="rust")
    payload = json.loads(out)
    assert payload["applied"] is True
    finding = payload["language_findings"][0]
    assert finding["code"] == "verify_summary"
    assert "runnables=2" in finding["message"]
    assert "flycheck_diagnostics=0" in finding["message"]


def test_verify_after_refactor_workspace_boundary_blocked(tmp_path: Path):
    tool = _make_tool(VerifyAfterRefactorTool, tmp_path)
    out = tool.apply(
        file=str(tmp_path.parent / "elsewhere.rs"), language="rust",
    )
    assert json.loads(out)["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


# ---------- Re-export + boundary sanity ------------------------------------


def test_all_four_tools_reexported_from_serena_tools():
    import serena.tools as tools_module
    for name in (
        "GenerateTraitImplScaffoldTool",
        "GenerateMemberTool",
        "ExpandMacroTool",
        "VerifyAfterRefactorTool",
    ):
        assert hasattr(tools_module, name)


def test_apply_methods_invoke_workspace_boundary_guard():
    for cls in (
        GenerateTraitImplScaffoldTool,
        GenerateMemberTool,
        ExpandMacroTool,
        VerifyAfterRefactorTool,
    ):
        src = get_apply_source(cls)
        assert "workspace_boundary_guard(" in src, (
            f"{cls.__name__}.apply must call workspace_boundary_guard()"
        )


def test_tool_names_match_scope_report_naming():
    expected = {
        GenerateTraitImplScaffoldTool: "generate_trait_impl_scaffold",
        GenerateMemberTool: "generate_member",
        ExpandMacroTool: "expand_macro",
        VerifyAfterRefactorTool: "verify_after_refactor",
    }
    for cls, name in expected.items():
        assert cls.get_name_from_cls() == name
