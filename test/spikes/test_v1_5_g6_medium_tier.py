"""v1.5 G6 — MEDIUM tier sweep (ME-1 .. ME-7).

Each sub-task has one focused acid test that asserts the previously-
discarded argument now reaches the LSP request OR is honestly surfaced
via INPUT_NOT_HONORED envelope. ME-5 + ME-7 are verified-no-change
(covered by L-G1 / L-G4-6 regression suites).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    AutoImportSpecializedTool,
    GenerateConstructorTool,
    IntroduceParameterTool,
    OverrideMethodsTool,
    TidyStructureTool,
    _java_generate_dispatch,
)
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make(cls, project_root: Path) -> Any:
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


# --- ME-1: tidy_structure honors scope ----------------------------------


def test_me_1_tidy_structure_scope_impl_dispatches_only_reorder_impl_items(tmp_path):
    """scope='impl' must dispatch ONLY refactor.rewrite.reorder_impl_items
    (not sort_items or reorder_fields)."""
    src = tmp_path / "lib.rs"
    src.write_text("impl Foo {}\n")
    tool = _make(TidyStructureTool, tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True
    captured: list[str] = []

    async def _actions(**kw):
        captured.append((kw.get("only") or [""])[0])
        return []

    fake_coord.merge_code_actions = _actions
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        tool.apply(
            file=str(src), scope="impl", language="rust",
            position={"line": 0, "character": 0},
        )
    assert captured == ["refactor.rewrite.reorder_impl_items"], captured


def test_me_1_tidy_structure_scope_type_dispatches_only_reorder_fields(tmp_path):
    """scope='type' must dispatch ONLY refactor.rewrite.reorder_fields."""
    src = tmp_path / "lib.rs"
    src.write_text("struct Foo { a: i32, b: i32 }\n")
    tool = _make(TidyStructureTool, tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True
    captured: list[str] = []

    async def _actions(**kw):
        captured.append((kw.get("only") or [""])[0])
        return []

    fake_coord.merge_code_actions = _actions
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        tool.apply(
            file=str(src), scope="type", language="rust",
            position={"line": 0, "character": 7},
        )
    assert captured == ["refactor.rewrite.reorder_fields"], captured


def test_me_1_tidy_structure_scope_file_dispatches_all_three_kinds(tmp_path):
    """scope='file' (the default) dispatches all 3 kinds — preserves the
    pre-G6 behavior for back-compat."""
    src = tmp_path / "lib.rs"
    src.write_text("// hi\n")
    tool = _make(TidyStructureTool, tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True
    captured: list[str] = []

    async def _actions(**kw):
        captured.append((kw.get("only") or [""])[0])
        return []

    fake_coord.merge_code_actions = _actions
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        tool.apply(file=str(src), scope="file", language="rust")
    assert set(captured) == {
        "refactor.rewrite.reorder_impl_items",
        "refactor.rewrite.sort_items",
        "refactor.rewrite.reorder_fields",
    }, captured


# --- ME-2: auto_import_specialized honors symbol_name -------------------


def test_me_2_auto_import_specialized_threads_symbol_name_as_title_match(tmp_path):
    """When rope returns multiple `from <pkg> import compute` candidates,
    the caller's symbol_name=<pkg> selects the right one."""
    src = tmp_path / "calc.py"
    src.write_text("x = compute()\n")
    tool = _make(AutoImportSpecializedTool, tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    a1 = MagicMock(
        id="rope:1", action_id="rope:1",
        title="from numpy import compute",
        kind="quickfix.import", is_preferred=False, provenance="pylsp-rope",
    )
    a2 = MagicMock(
        id="rope:2", action_id="rope:2",
        title="from scipy import compute",
        kind="quickfix.import", is_preferred=False, provenance="pylsp-rope",
    )

    async def _actions(**_kw):
        return [a1, a2]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: (
        {"changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 0, "character": 0}},
            "newText": "from numpy import compute\n",
        }]}} if aid == "rope:1" else (
            {"changes": {src.as_uri(): [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 0}},
                "newText": "from scipy import compute\n",
            }]}} if aid == "rope:2" else None
        )
    )

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 4},
            symbol_name="numpy",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    body = src.read_text(encoding="utf-8")
    assert "from numpy import compute" in body, body
    assert "from scipy import compute" not in body, body


def test_me_2_auto_import_specialized_input_not_honored_when_symbol_name_missing(tmp_path):
    """No candidate's title matches caller's symbol_name → INPUT_NOT_HONORED."""
    src = tmp_path / "calc.py"
    src.write_text("x = compute()\n")
    tool = _make(AutoImportSpecializedTool, tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    a1 = MagicMock(
        id="rope:1", action_id="rope:1",
        title="from scipy import compute",
        kind="quickfix.import", is_preferred=False, provenance="pylsp-rope",
    )

    async def _actions(**_kw):
        return [a1]

    fake_coord.merge_code_actions = _actions

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 4},
            symbol_name="numpy",
            language="python",
        )
    payload = json.loads(out)
    assert payload.get("status") == "skipped", payload
    assert payload.get("reason") == "no_candidate_matched_title_match", payload


# --- ME-3: introduce_parameter substitutes parameter_name ---------------


def test_me_3_introduce_parameter_substitutes_caller_name(tmp_path):
    """Rope emits `def f(p=42)` (auto-name `p`); the facade post-processes
    the WorkspaceEdit to substitute the caller's parameter_name."""
    src = tmp_path / "calc.py"
    src.write_text("def f():\n    return 42\n")
    tool = _make(IntroduceParameterTool, tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True
    a = MagicMock(
        id="rope:1", action_id="rope:1",
        title="Introduce parameter p",
        kind="refactor.rewrite.introduce_parameter",
        is_preferred=False, provenance="pylsp-rope",
    )

    async def _actions(**_kw):
        return [a]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {
        "changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 0},
                      "end": {"line": 1, "character": 0}},
            "newText": "def f(p=42):\n",
        }]},
    }

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 1, "character": 11},
            parameter_name="answer",
            language="python",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    body = src.read_text(encoding="utf-8")
    assert "answer=42" in body, body
    assert "p=42" not in body, body


# --- ME-4: generate_constructor + override_methods INPUT_NOT_HONORED ----


def test_me_4_generate_constructor_input_not_honored_when_include_fields_set(tmp_path):
    """When caller passes include_fields=['name'], jdtls picker isn't wired
    in v1.5 P2 — surface INPUT_NOT_HONORED instead of silently using all
    fields."""
    src = tmp_path / "Foo.java"
    src.write_text("class Foo { String name; int age; }\n")
    tool = _make(GenerateConstructorTool, tmp_path)
    out = tool.apply(
        file=str(src), class_name_path="Foo",
        include_fields=["name"], language="java",
    )
    payload = json.loads(out)
    assert payload.get("status") == "skipped", payload
    reason = payload.get("reason") or ""
    assert "include_fields" in reason, payload


def test_me_4_generate_constructor_no_include_fields_preserves_default(tmp_path):
    """include_fields=None preserves today's behavior (jdtls default)."""
    src = tmp_path / "Foo.java"
    src.write_text("class Foo { String name; }\n")
    tool = _make(GenerateConstructorTool, tmp_path)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _find(**_kw):
        return {"start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 5}}

    fake_coord.find_symbol_range = _find

    async def _actions(**_kw):
        return [MagicMock(id="jdtls:1", action_id="jdtls:1",
                          title="Generate constructor", kind="source.generate.constructor",
                          provenance="jdtls", is_preferred=False)]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: None  # legacy path → empty checkpoint

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src), class_name_path="Foo",
            include_fields=None, language="java",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload


def test_me_4_override_methods_input_not_honored_when_method_names_set(tmp_path):
    """method_names=['toString'] surfaces INPUT_NOT_HONORED in v1.5 P2."""
    src = tmp_path / "Bar.java"
    src.write_text("class Bar extends Object {}\n")
    tool = _make(OverrideMethodsTool, tmp_path)
    out = tool.apply(
        file=str(src), class_name_path="Bar",
        method_names=["toString"], language="java",
    )
    payload = json.loads(out)
    assert payload.get("status") == "skipped", payload
    assert "method_names" in (payload.get("reason") or ""), payload


# --- ME-6: java_generate_dispatch fails honestly on unresolvable class --


def test_me_6_java_generate_dispatch_fails_when_class_unresolvable(tmp_path):
    src = tmp_path / "Bar.java"
    src.write_text("class Bar {}\n")
    fake_coord = MagicMock()

    async def _find(**_kw):
        return None

    fake_coord.find_symbol_range = _find

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = _java_generate_dispatch(
            stage_name="scalpel_test",
            file=str(src),
            class_name_path="Nonexistent",
            kind="source.generate.constructor",
            project_root=tmp_path,
            preview=False,
            allow_out_of_workspace=False,
        )
    payload = json.loads(out)
    assert payload["applied"] is False, payload
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND", payload
