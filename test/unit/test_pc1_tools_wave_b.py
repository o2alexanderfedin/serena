"""PC1 coverage uplift – Wave B.

Covers workspace-boundary / early-exit / pure-Python paths in the
Tools that were not covered by the Wave A files:

  - CompleteMatchArmsTool, ExtractLifetimeTool, ExpandGlobImportsTool,
    GenerateTraitImplScaffoldTool, GenerateMemberTool
  - ExpandMacroTool (non-rust lang, dry_run short-circuit)
  - VerifyAfterRefactorTool (non-rust lang, dry_run short-circuit)
  - ConvertToMethodObjectTool, LocalToFieldTool, UseFunctionTool,
    IntroduceParameterTool, GenerateFromUndefinedTool,
    AutoImportSpecializedTool, IgnoreDiagnosticTool
  - ConvertToAsyncTool (FileNotFoundError / ValueError paths)
  - AnnotateReturnTypeTool (workspace boundary)
  - ConvertFromRelativeImportsTool (workspace boundary + FileNotFoundError)
  - _find_heading_position (pure function)
  - RenameHeadingTool (workspace boundary, heading not found)
  - SplitDocTool (workspace boundary, no-op, dry_run)
  - ExtractSectionTool (workspace boundary, KeyError, dry_run)
  - OrganizeLinksTool (workspace boundary, no-op, dry_run)
  - GenerateConstructorTool / OverrideMethodsTool (include_fields/method_names,
    non-java language)
  - _java_generate_dispatch (boundary violation)
  - _apply_markdown_workspace_edit (create + text-edit path)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# CompleteMatchArmsTool — workspace boundary
# ---------------------------------------------------------------------------


def test_complete_match_arms_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import CompleteMatchArmsTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(CompleteMatchArmsTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "lib.rs"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# ExtractLifetimeTool — workspace boundary
# ---------------------------------------------------------------------------


def test_extract_lifetime_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ExtractLifetimeTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ExtractLifetimeTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "lib.rs"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# ExpandGlobImportsTool — workspace boundary
# ---------------------------------------------------------------------------


def test_expand_glob_imports_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ExpandGlobImportsTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ExpandGlobImportsTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "lib.rs"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# GenerateTraitImplScaffoldTool — workspace boundary
# ---------------------------------------------------------------------------


def test_generate_trait_impl_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import GenerateTraitImplScaffoldTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(GenerateTraitImplScaffoldTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "lib.rs"),
            position={"line": 0, "character": 0},
            trait_name="Display",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# GenerateMemberTool — unknown member_kind + workspace boundary
# ---------------------------------------------------------------------------


def test_generate_member_unknown_kind_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import GenerateMemberTool

    tool = object.__new__(GenerateMemberTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "lib.rs"
    f.write_text("struct Foo { val: i32 }")

    result = tool.apply(
        file=str(f),
        position={"line": 0, "character": 0},
        member_kind="unknown_kind",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_generate_member_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import GenerateMemberTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(GenerateMemberTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        # member_kind validated FIRST; pass a valid value
        result = tool.apply(
            file=str(other / "lib.rs"),
            position={"line": 0, "character": 0},
            member_kind="getter",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# ExpandMacroTool — non-rust language, dry_run short-circuit
# ---------------------------------------------------------------------------


def test_expand_macro_non_rust_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ExpandMacroTool

    tool = object.__new__(ExpandMacroTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "main.py"
    f.write_text("print('hello')")

    result = tool.apply(
        file=str(f),
        position={"line": 0, "character": 0},
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_expand_macro_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ExpandMacroTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ExpandMacroTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "lib.rs"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_expand_macro_dry_run_returns_preview_token(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ExpandMacroTool

    tool = object.__new__(ExpandMacroTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "lib.rs"
    f.write_text("println!(\"{}\", 42);")

    result = tool.apply(
        file=str(f),
        position={"line": 0, "character": 0},
        dry_run=True,
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert "preview_token" in payload


# ---------------------------------------------------------------------------
# VerifyAfterRefactorTool — non-rust language, dry_run short-circuit
# ---------------------------------------------------------------------------


def test_verify_after_refactor_non_rust_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import VerifyAfterRefactorTool

    tool = object.__new__(VerifyAfterRefactorTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "main.py"
    f.write_text("def foo(): pass")

    result = tool.apply(
        file=str(f),
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_verify_after_refactor_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import VerifyAfterRefactorTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(VerifyAfterRefactorTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "lib.rs"),
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_verify_after_refactor_dry_run_returns_preview_token(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import VerifyAfterRefactorTool

    tool = object.__new__(VerifyAfterRefactorTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "lib.rs"
    f.write_text("fn foo() {}")

    result = tool.apply(
        file=str(f),
        dry_run=True,
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert "preview_token" in payload


# ---------------------------------------------------------------------------
# ConvertToMethodObjectTool — workspace boundary
# ---------------------------------------------------------------------------


def test_convert_to_method_object_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ConvertToMethodObjectTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ConvertToMethodObjectTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# LocalToFieldTool — workspace boundary
# ---------------------------------------------------------------------------


def test_local_to_field_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import LocalToFieldTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(LocalToFieldTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# UseFunctionTool — workspace boundary
# ---------------------------------------------------------------------------


def test_use_function_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import UseFunctionTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(UseFunctionTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# IntroduceParameterTool — workspace boundary
# ---------------------------------------------------------------------------


def test_introduce_parameter_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import IntroduceParameterTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(IntroduceParameterTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# GenerateFromUndefinedTool — workspace boundary
# ---------------------------------------------------------------------------


def test_generate_from_undefined_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import GenerateFromUndefinedTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(GenerateFromUndefinedTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# AutoImportSpecializedTool — workspace boundary
# ---------------------------------------------------------------------------


def test_auto_import_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import AutoImportSpecializedTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(AutoImportSpecializedTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            position={"line": 0, "character": 0},
            symbol_name="Path",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# IgnoreDiagnosticTool — unknown tool_name + workspace boundary
# ---------------------------------------------------------------------------


def test_ignore_diagnostic_unknown_tool_name(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import IgnoreDiagnosticTool

    tool = object.__new__(IgnoreDiagnosticTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "main.py"
    f.write_text("x = 1")

    result = tool.apply(
        file=str(f),
        position={"line": 0, "character": 0},
        tool_name="mypy",  # not in _IGNORE_DIAGNOSTIC_KIND_BY_TOOL
        rule="F401",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_ignore_diagnostic_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import IgnoreDiagnosticTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(IgnoreDiagnosticTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        # tool_name validated FIRST; pass a valid one
        result = tool.apply(
            file=str(other / "main.py"),
            position={"line": 0, "character": 0},
            tool_name="ruff",
            rule="F401",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# ConvertToAsyncTool — workspace boundary, FileNotFoundError, ValueError
# ---------------------------------------------------------------------------


def test_convert_to_async_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ConvertToAsyncTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ConvertToAsyncTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            symbol="foo",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_convert_to_async_file_not_found_returns_failure(tmp_path: Path) -> None:
    """FileNotFoundError from convert_function_to_async → INVALID_ARGUMENT."""
    from serena.tools.scalpel_facades import ConvertToAsyncTool
    import serena.refactoring.python_async_conversion as _mod

    tool = object.__new__(ConvertToAsyncTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    nonexistent = tmp_path / "ghost.py"  # does not exist

    # Patch at the module level where the facade does its import
    with patch.object(_mod, "convert_function_to_async",
                      side_effect=FileNotFoundError("ghost.py not found")):
        result = tool.apply(
            file=str(nonexistent),
            symbol="foo",
            allow_out_of_workspace=True,
        )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_convert_to_async_value_error_returns_failure(tmp_path: Path) -> None:
    """Symbol not found in file → ValueError → SYMBOL_NOT_FOUND."""
    from serena.tools.scalpel_facades import ConvertToAsyncTool
    import serena.refactoring.python_async_conversion as _mod

    tool = object.__new__(ConvertToAsyncTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "main.py"
    f.write_text("def bar(): pass")

    with patch.object(_mod, "convert_function_to_async",
                      side_effect=ValueError("symbol not found")):
        result = tool.apply(
            file=str(f),
            symbol="nonexistent",
            allow_out_of_workspace=True,
        )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------------------------------------------------------------------------
# AnnotateReturnTypeTool — workspace boundary
# ---------------------------------------------------------------------------


def test_annotate_return_type_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import AnnotateReturnTypeTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(AnnotateReturnTypeTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            symbol="foo",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# ConvertFromRelativeImportsTool — workspace boundary + FileNotFoundError
# ---------------------------------------------------------------------------


def test_convert_from_relative_imports_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ConvertFromRelativeImportsTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ConvertFromRelativeImportsTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "main.py"),
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_convert_from_relative_imports_file_not_found(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ConvertFromRelativeImportsTool

    tool = object.__new__(ConvertFromRelativeImportsTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    nonexistent = tmp_path / "ghost.py"

    with patch.dict(
        "sys.modules",
        {
            "serena.refactoring.python_imports_relative":
                type("M", (), {"convert_from_relative_imports":
                    MagicMock(side_effect=FileNotFoundError("ghost.py not found"))})(),
        },
    ):
        result = tool.apply(
            file=str(nonexistent),
            allow_out_of_workspace=True,
        )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


# ---------------------------------------------------------------------------
# _find_heading_position — pure function
# ---------------------------------------------------------------------------


def test_find_heading_position_returns_correct_coords(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import _find_heading_position

    f = tmp_path / "doc.md"
    f.write_text("# Introduction\n\nSome text.\n\n## Details\n")

    pos = _find_heading_position(f, "Introduction")
    assert pos is not None
    assert pos["line"] == 0
    assert pos["character"] == 2  # after "# "

    pos2 = _find_heading_position(f, "Details")
    assert pos2 is not None
    assert pos2["line"] == 4


def test_find_heading_position_missing_heading_returns_none(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import _find_heading_position

    f = tmp_path / "doc.md"
    f.write_text("# Hello\n")

    result = _find_heading_position(f, "NotHere")
    assert result is None


def test_find_heading_position_missing_file_returns_none(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import _find_heading_position

    result = _find_heading_position(tmp_path / "nonexistent.md", "Anything")
    assert result is None


# ---------------------------------------------------------------------------
# RenameHeadingTool — workspace boundary + heading not found
# ---------------------------------------------------------------------------


def test_rename_heading_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import RenameHeadingTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(RenameHeadingTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "README.md"),
            heading="Hello",
            new_name="World",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_rename_heading_not_found_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import RenameHeadingTool

    tool = object.__new__(RenameHeadingTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "doc.md"
    f.write_text("# Introduction\n\nBody.\n")

    result = tool.apply(
        file=str(f),
        heading="NonExistentSection",
        new_name="NewName",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


# ---------------------------------------------------------------------------
# SplitDocTool — workspace boundary, no-op (no headings), dry_run
# ---------------------------------------------------------------------------


def test_split_doc_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import SplitDocTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(SplitDocTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "doc.md"),
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_split_doc_no_headings_returns_no_op(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import SplitDocTool

    tool = object.__new__(SplitDocTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "doc.md"
    f.write_text("Just plain text without any headings.\n")

    result = tool.apply(
        file="doc.md",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["no_op"] is True


def test_split_doc_dry_run_with_headings_returns_preview_token(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import SplitDocTool

    tool = object.__new__(SplitDocTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "doc.md"
    f.write_text("# Section One\n\nContent.\n\n# Section Two\n\nMore content.\n")

    result = tool.apply(
        file="doc.md",
        dry_run=True,
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert "preview_token" in payload


# ---------------------------------------------------------------------------
# ExtractSectionTool — workspace boundary, KeyError (heading missing), dry_run
# ---------------------------------------------------------------------------


def test_extract_section_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ExtractSectionTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ExtractSectionTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "doc.md"),
            heading="Introduction",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_extract_section_heading_not_found_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ExtractSectionTool

    tool = object.__new__(ExtractSectionTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "doc.md"
    f.write_text("# Real Section\n\nContent here.\n")

    result = tool.apply(
        file="doc.md",
        heading="Ghost Section",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


def test_extract_section_dry_run_returns_preview_token(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ExtractSectionTool

    tool = object.__new__(ExtractSectionTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "doc.md"
    f.write_text("# Real Section\n\nContent here.\n")

    result = tool.apply(
        file="doc.md",
        heading="Real Section",
        dry_run=True,
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert "preview_token" in payload


# ---------------------------------------------------------------------------
# OrganizeLinksTool — workspace boundary + no-op (no links)
# ---------------------------------------------------------------------------


def test_organize_links_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import OrganizeLinksTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(OrganizeLinksTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "doc.md"),
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_organize_links_no_links_returns_no_op(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import OrganizeLinksTool

    tool = object.__new__(OrganizeLinksTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "doc.md"
    f.write_text("Just plain text. No links here.\n")

    result = tool.apply(
        file="doc.md",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["no_op"] is True


# ---------------------------------------------------------------------------
# GenerateConstructorTool — include_fields short-circuit + non-java language
# ---------------------------------------------------------------------------


def test_generate_constructor_include_fields_returns_skipped(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import GenerateConstructorTool

    tool = object.__new__(GenerateConstructorTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    result = tool.apply(
        file=str(tmp_path / "Foo.java"),
        class_name_path="Foo",
        include_fields=["name", "age"],
    )
    payload = json.loads(result)
    assert payload["status"] == "skipped"
    assert "include_fields" in payload["reason"]


def test_generate_constructor_non_java_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import GenerateConstructorTool

    tool = object.__new__(GenerateConstructorTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    result = tool.apply(
        file=str(tmp_path / "Foo.py"),
        class_name_path="Foo",
        include_fields=None,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


# ---------------------------------------------------------------------------
# OverrideMethodsTool — method_names short-circuit + non-java language
# ---------------------------------------------------------------------------


def test_override_methods_method_names_returns_skipped(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import OverrideMethodsTool

    tool = object.__new__(OverrideMethodsTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    result = tool.apply(
        file=str(tmp_path / "Foo.java"),
        class_name_path="Foo",
        method_names=["toString", "equals"],
    )
    payload = json.loads(result)
    assert payload["status"] == "skipped"
    assert "method_names" in payload["reason"]


def test_override_methods_non_java_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import OverrideMethodsTool

    tool = object.__new__(OverrideMethodsTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    result = tool.apply(
        file=str(tmp_path / "Foo.py"),
        class_name_path="Foo",
        method_names=None,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


# ---------------------------------------------------------------------------
# _apply_markdown_workspace_edit — create + text-edit path
# ---------------------------------------------------------------------------


def test_apply_markdown_workspace_edit_create_and_text_edit(tmp_path: Path) -> None:
    """_apply_markdown_workspace_edit should create files and apply text edits."""
    from serena.tools.scalpel_facades import _apply_markdown_workspace_edit

    new_file = tmp_path / "section.md"
    existing = tmp_path / "doc.md"
    existing.write_text("old content\n")

    workspace_edit: dict[str, Any] = {
        "documentChanges": [
            # CreateFile operation
            {"kind": "create", "uri": new_file.as_uri()},
            # TextDocumentEdit for the existing file
            {
                "textDocument": {"uri": existing.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 1_000_000_000, "character": 0},
                        },
                        "newText": "new content\n",
                    }
                ],
            },
        ]
    }

    count = _apply_markdown_workspace_edit(workspace_edit)
    assert count >= 0  # should not raise

    # The created file should exist (empty)
    assert new_file.exists()
    # The existing file should have new content
    assert existing.read_text() == "new content\n"


def test_apply_markdown_workspace_edit_empty_changes(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import _apply_markdown_workspace_edit

    result = _apply_markdown_workspace_edit({"documentChanges": []})
    assert result == 0


def test_apply_markdown_workspace_edit_non_dict_entry_skipped(tmp_path: Path) -> None:
    """Non-dict entries in documentChanges are skipped without error."""
    from serena.tools.scalpel_facades import _apply_markdown_workspace_edit

    # Should not raise
    result = _apply_markdown_workspace_edit({"documentChanges": ["not_a_dict", 42]})
    assert result == 0
