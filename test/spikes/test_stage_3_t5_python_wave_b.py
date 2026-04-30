"""Stage 3 T5 — Python ergonomic facades wave B (multi-source).

Per scope-report §4.4:
- ScalpelGenerateFromUndefinedTool (§4.4.1 row 8) — pylsp-rope
  ``quickfix.generate``.
- ScalpelAutoImportSpecializedTool (§4.4.1 implicit) — pylsp-rope
  ``addImport`` two-step flow.
- ScalpelFixLintsTool (§4.4.3 row 1) — ruff ``source.fixAll.ruff``;
  **closes the E13-py organize_imports dedup product gap** surfaced by
  v0.2.0-critical-path A. ruff's ``source.organizeImports`` does NOT
  remove duplicate imports — that's I001, a lint rule. ``source.fixAll.ruff``
  applies all fixable lints including I001.
- ScalpelIgnoreDiagnosticTool (§4.4.2 row 3) — basedpyright/ruff
  inline ignore-comment insertion (``# pyright: ignore[<rule>]``,
  ``# noqa: <rule>``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.facade_support import get_apply_source
from serena.tools.scalpel_facades import (
    ScalpelAutoImportSpecializedTool,
    ScalpelFixLintsTool,
    ScalpelGenerateFromUndefinedTool,
    ScalpelIgnoreDiagnosticTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(cls: type, project_root: Path) -> Any:
    """Construct a Tool-subclass instance without invoking ``__init__``.

    Returns ``Any`` so test bodies can call each subclass's bespoke
    ``apply(...)`` signature directly without per-call type assertions —
    pyright's narrowing through ``__new__`` does not reach subclass
    ``apply`` parameter shapes (e.g. ``symbol_name``, ``tool_name``).
    """
    tool = cls.__new__(cls)  # pyright: ignore[reportCallIssue]
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _fake_action(
    kind: str,
    provenance: str = "pylsp-rope",
    title: str = "x",
    diagnostics: tuple[Any, ...] = (),
):
    """Fake LSP code action.

    v1.6 P5 added post-merge action filters on ``scalpel_generate_from_undefined``
    (title prefix) and ``scalpel_ignore_diagnostic`` (diagnostic code). Tests
    now pass ``title=`` / ``diagnostics=`` so the fake action survives those
    filters when the dispatch is being exercised.
    """
    return MagicMock(
        action_id=f"{provenance}:{kind}",
        title=title, kind=kind, provenance=provenance,
        diagnostics=diagnostics,
    )


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


# ---------- ScalpelGenerateFromUndefinedTool -------------------------------


def test_generate_from_undefined_dispatches(tmp_path: Path):
    # v1.5 G4-5 — facade prefers the granular ``quickfix.generate.<kind>``
    # when rope advertises it, otherwise falls back to the flat
    # ``quickfix.generate`` umbrella kind. ``supports_kind`` is pinned so
    # only the umbrella kind is advertised — the test exercises the
    # fallback path explicitly.
    # v1.6 P5 — title-prefix filter on the fallback discards sibling
    # ``class``/``variable`` actions. ``target_kind="function"`` plus an
    # action whose title starts with "function" survives the filter.
    src = tmp_path / "module.py"
    src.write_text("x = undefined_thing()\n")
    tool = _make_tool(ScalpelGenerateFromUndefinedTool, tmp_path)
    coord = _fake_coord({
        "quickfix.generate": [_fake_action(
            "quickfix.generate", title="function: generate undefined_thing",
        )],
    })
    coord.supports_kind = lambda lang, kind: kind == "quickfix.generate"
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 4},
            target_kind="function", language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_generate_from_undefined_no_action(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("\n")
    tool = _make_tool(ScalpelGenerateFromUndefinedTool, tmp_path)
    coord = _fake_coord({})
    coord.supports_kind = lambda lang, kind: kind == "quickfix.generate"
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            target_kind="function", language="python",
        )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- ScalpelAutoImportSpecializedTool -------------------------------


def test_auto_import_specialized_picks_first_candidate(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("Path('/')\n")
    tool = _make_tool(ScalpelAutoImportSpecializedTool, tmp_path)
    # v1.5 G6 ME-2 — symbol_name now flows into title_match. Both fake
    # actions need a title containing 'Path' for the dispatcher to
    # accept either. Test still asserts both candidates were surfaced
    # (count==2) — the dispatcher's MULTIPLE_CANDIDATES envelope kicks
    # in only when ≥2 hits match the substring; that's tested in
    # test_v1_5_g6_medium_tier.py. Here we have one match (the second
    # fake's title 'X' is excluded), so dispatcher selects uniquely.
    a1 = _fake_action("quickfix.import")
    a1.title = "from pathlib import Path"
    a2 = _fake_action("quickfix.import")
    a2.title = "X"  # does NOT match symbol_name='Path'
    coord = _fake_coord({"quickfix.import": [a1, a2]})
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            symbol_name="Path", language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["lsp_ops"][0]["count"] == 2


def test_auto_import_specialized_no_action(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("\n")
    tool = _make_tool(ScalpelAutoImportSpecializedTool, tmp_path)
    coord = _fake_coord({})
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            symbol_name="Missing", language="python",
        )
    payload = json.loads(out)
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------- ScalpelFixLintsTool (closes E13-py gap) ------------------------


def test_fix_lints_uses_source_fixall_ruff(tmp_path: Path):
    """E13-py: source.fixAll.ruff dedups duplicate imports (I001)."""
    src = tmp_path / "module.py"
    src.write_text("import sys\nimport os\nimport sys\n")
    tool = _make_tool(ScalpelFixLintsTool, tmp_path)
    seen_kinds: list[list[str]] = []
    coord = MagicMock()

    async def _merge(**kwargs):
        seen_kinds.append(list(kwargs.get("only", [])))
        return [_fake_action("source.fixAll.ruff", provenance="ruff")]
    coord.merge_code_actions = _merge
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(file=str(src), language="python")
    payload = json.loads(out)
    assert payload["applied"] is True
    # Verify we actually requested source.fixAll.ruff (not just organizeImports).
    flat_kinds = [k for batch in seen_kinds for k in batch]
    assert "source.fixAll.ruff" in flat_kinds


def test_fix_lints_no_op_when_clean(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("x = 1\n")
    tool = _make_tool(ScalpelFixLintsTool, tmp_path)
    coord = _fake_coord({})
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(file=str(src), language="python")
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["no_op"] is True


def test_fix_lints_dry_run(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("import sys\nimport sys\n")
    tool = _make_tool(ScalpelFixLintsTool, tmp_path)
    coord = _fake_coord({
        "source.fixAll.ruff": [_fake_action("source.fixAll.ruff", provenance="ruff")],
    })
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(file=str(src), language="python", dry_run=True)
    payload = json.loads(out)
    assert payload["preview_token"] is not None


# ---------- ScalpelIgnoreDiagnosticTool ------------------------------------


def test_ignore_diagnostic_pyright_dispatches(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("undefined_name\n")
    tool = _make_tool(ScalpelIgnoreDiagnosticTool, tmp_path)
    # v1.5 G4-10 + v1.6 P5: the facade now uses an OR-shape filter that
    # matches on EITHER action.title (v1.5 substring) OR action.diagnostics
    # (v1.6 code-equality). The canonical fixture shape — also adopted by
    # the v1.9 routing benchmark — supplies a diagnostic, since real
    # basedpyright/ruff responses always carry the diagnostic on the
    # quickfix action.
    diag = MagicMock(code="reportUndefinedVariable")
    coord = _fake_coord({
        "quickfix.pyright_ignore": [_fake_action(
            "quickfix.pyright_ignore", provenance="basedpyright",
            diagnostics=(diag,),
        )],
    })
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            tool_name="pyright", rule="reportUndefinedVariable",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_ignore_diagnostic_ruff_dispatches(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("import sys\n")
    tool = _make_tool(ScalpelIgnoreDiagnosticTool, tmp_path)
    # v1.5 G4-10 + v1.6 P5: see ``test_ignore_diagnostic_pyright_dispatches``
    # for the OR-shape filter rationale; canonical fixture supplies the
    # diagnostic code that real ruff responses always carry.
    diag = MagicMock(code="F401")
    coord = _fake_coord({
        "quickfix.ruff_noqa": [_fake_action(
            "quickfix.ruff_noqa", provenance="ruff",
            diagnostics=(diag,),
        )],
    })
    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=coord):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 0},
            tool_name="ruff", rule="F401",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True


def test_ignore_diagnostic_unknown_tool_returns_invalid_argument(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("\n")
    tool = _make_tool(ScalpelIgnoreDiagnosticTool, tmp_path)
    out = tool.apply(
        file=str(src), position={"line": 0, "character": 0},
        tool_name="bogus", rule="x", language="python",
    )
    assert json.loads(out)["failure"]["code"] == "INVALID_ARGUMENT"


# ---------- Re-export + boundary sanity ------------------------------------


def test_all_four_tools_reexported_from_serena_tools():
    import serena.tools as tools_module
    for name in (
        "ScalpelGenerateFromUndefinedTool",
        "ScalpelAutoImportSpecializedTool",
        "ScalpelFixLintsTool",
        "ScalpelIgnoreDiagnosticTool",
    ):
        assert hasattr(tools_module, name)


def test_apply_methods_invoke_workspace_boundary_guard():
    for cls in (
        ScalpelGenerateFromUndefinedTool,
        ScalpelAutoImportSpecializedTool,
        ScalpelFixLintsTool,
        ScalpelIgnoreDiagnosticTool,
    ):
        src = get_apply_source(cls)
        assert "workspace_boundary_guard(" in src, (
            f"{cls.__name__}.apply must call workspace_boundary_guard()"
        )


def test_tool_names_match_scope_report_naming():
    expected = {
        ScalpelGenerateFromUndefinedTool: "scalpel_generate_from_undefined",
        ScalpelAutoImportSpecializedTool: "scalpel_auto_import_specialized",
        ScalpelFixLintsTool: "scalpel_fix_lints",
        ScalpelIgnoreDiagnosticTool: "scalpel_ignore_diagnostic",
    }
    for cls, name in expected.items():
        assert cls.get_name_from_cls() == name
