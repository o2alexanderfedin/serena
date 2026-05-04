"""PC1 — unit tests for scalpel_facades.py dispatch logic.

Covers uncovered decision branches in:
- _infer_language / _infer_extract_language
- _merge_workspace_edits
- _post_process_extract_edit
- _substitute_introduced_parameter_name
- _filter_definition_deletion_hunks (InlineTool helper)
- _select_candidate_action (G1 disambiguation)
- _dispatch_single_kind_facade (language gate, supports_kind, dry_run)
- _capability_not_available_envelope
- SplitFileTool.apply (workspace guard, empty groups, unknown language)
- ExtractTool.apply (range/name_path, invalid target, invalid language, target validity matrix)
- ConvertModuleLayoutTool.apply (bad target_layout)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from serena.tools.scalpel_facades import (
    _EXTRACT_TARGET_TO_KIND,
    _EXTRACT_VALID_TARGETS_BY_LANGUAGE,
    _capability_not_available_envelope,
    _dispatch_single_kind_facade,
    _filter_definition_deletion_hunks,
    _infer_extract_language,
    _infer_language,
    _merge_workspace_edits,
    _post_process_extract_edit,
    _select_candidate_action,
    _substitute_introduced_parameter_name,
    ConvertModuleLayoutTool,
    ExtractTool,
    SplitFileTool,
)
from serena.tools.scalpel_schemas import ErrorCode


# ---------------------------------------------------------------------------
# _infer_language
# ---------------------------------------------------------------------------


def test_infer_language_explicit_overrides_extension() -> None:
    result = _infer_language("foo.rs", explicit="python")
    assert result == "python"


def test_infer_language_rust_from_extension() -> None:
    result = _infer_language("src/main.rs", explicit=None)
    assert result == "rust"


def test_infer_language_python_py() -> None:
    result = _infer_language("module.py", explicit=None)
    assert result == "python"


def test_infer_language_python_pyi() -> None:
    result = _infer_language("stubs.pyi", explicit=None)
    assert result == "python"


def test_infer_language_unknown_extension() -> None:
    result = _infer_language("file.java", explicit=None)
    assert result == "unknown"


# ---------------------------------------------------------------------------
# _infer_extract_language
# ---------------------------------------------------------------------------


def test_infer_extract_language_java_from_extension() -> None:
    result = _infer_extract_language("Main.java", explicit=None)
    assert result == "java"


def test_infer_extract_language_explicit_overrides() -> None:
    result = _infer_extract_language("Main.java", explicit="rust")
    assert result == "rust"


def test_infer_extract_language_rust() -> None:
    result = _infer_extract_language("lib.rs", explicit=None)
    assert result == "rust"


def test_infer_extract_language_unknown() -> None:
    result = _infer_extract_language("script.sh", explicit=None)
    assert result == "unknown"


# ---------------------------------------------------------------------------
# _merge_workspace_edits
# ---------------------------------------------------------------------------


def test_merge_workspace_edits_empty() -> None:
    result = _merge_workspace_edits([])
    assert result == {"documentChanges": []}


def test_merge_workspace_edits_document_changes_concatenated() -> None:
    e1 = {"documentChanges": [{"kind": "create", "uri": "file:///a.py"}]}
    e2 = {"documentChanges": [{"kind": "create", "uri": "file:///b.py"}]}
    result = _merge_workspace_edits([e1, e2])
    assert len(result["documentChanges"]) == 2


def test_merge_workspace_edits_changes_merged() -> None:
    e1 = {"changes": {"file:///a.py": [{"newText": "x"}]}}
    e2 = {"changes": {"file:///a.py": [{"newText": "y"}]}}
    result = _merge_workspace_edits([e1, e2])
    assert len(result["changes"]["file:///a.py"]) == 2


def test_merge_workspace_edits_different_files() -> None:
    e1 = {"changes": {"file:///a.py": [{"newText": "x"}]}}
    e2 = {"changes": {"file:///b.py": [{"newText": "y"}]}}
    result = _merge_workspace_edits([e1, e2])
    assert "file:///a.py" in result["changes"]
    assert "file:///b.py" in result["changes"]


# ---------------------------------------------------------------------------
# _post_process_extract_edit
# ---------------------------------------------------------------------------


def test_post_process_extract_edit_no_op_no_name_no_prefix() -> None:
    edit = {"changes": {"file:///f.rs": [{"range": {}, "newText": "fn new_function() {}"}]}}
    result = _post_process_extract_edit(edit, new_name=None, visibility_prefix="")
    assert result["changes"]["file:///f.rs"][0]["newText"] == "fn new_function() {}"


def test_post_process_extract_edit_renames_auto_name() -> None:
    edit = {"changes": {"file:///f.rs": [{"range": {}, "newText": "fn new_function() { new_function() }"}]}}
    result = _post_process_extract_edit(edit, new_name="my_func", visibility_prefix="")
    assert "my_func" in result["changes"]["file:///f.rs"][0]["newText"]
    assert "new_function" not in result["changes"]["file:///f.rs"][0]["newText"]


def test_post_process_extract_edit_injects_visibility_prefix() -> None:
    edit = {"changes": {"file:///f.rs": [{"range": {}, "newText": "fn new_function() {}"}]}}
    result = _post_process_extract_edit(edit, new_name=None, visibility_prefix="pub ")
    assert result["changes"]["file:///f.rs"][0]["newText"].startswith("pub fn")


def test_post_process_extract_edit_document_changes_shape() -> None:
    edit = {"documentChanges": [{
        "textDocument": {"uri": "file:///f.rs"},
        "edits": [{"range": {}, "newText": "fn new_function() {}"}],
    }]}
    result = _post_process_extract_edit(edit, new_name="my_fn", visibility_prefix="pub ")
    edited_text = result["documentChanges"][0]["edits"][0]["newText"]
    assert "my_fn" in edited_text
    assert "pub fn" in edited_text


def test_post_process_extract_edit_non_dict_passthrough() -> None:
    result = _post_process_extract_edit("not a dict", new_name="x", visibility_prefix="")  # type: ignore[arg-type]
    assert result == "not a dict"


def test_post_process_extract_edit_unknown_key_passed_through() -> None:
    edit = {"otherKey": "some value"}
    result = _post_process_extract_edit(edit, new_name=None, visibility_prefix="")
    assert result["otherKey"] == "some value"


def test_post_process_extract_edit_skips_non_string_new_text() -> None:
    edit = {"changes": {"file:///f.rs": [{"range": {}, "newText": 123}]}}
    result = _post_process_extract_edit(edit, new_name="x", visibility_prefix="pub ")
    # newText is int, not str — should pass through unchanged
    assert result["changes"]["file:///f.rs"][0]["newText"] == 123


def test_post_process_extract_edit_pub_crate_prefix() -> None:
    edit = {"changes": {"file:///f.rs": [{"range": {}, "newText": "fn new_function() {}"}]}}
    result = _post_process_extract_edit(edit, new_name=None, visibility_prefix="pub(crate) ")
    assert "pub(crate) fn" in result["changes"]["file:///f.rs"][0]["newText"]


# ---------------------------------------------------------------------------
# _substitute_introduced_parameter_name
# ---------------------------------------------------------------------------


def test_substitute_parameter_name_default_auto_name_no_op() -> None:
    edit = {"changes": {"file:///f.py": [{"range": {}, "newText": "def f(p): return p + 1"}]}}
    # "p" is in the auto-names list, so no substitution
    result = _substitute_introduced_parameter_name(edit, parameter_name="p")
    assert result == edit


def test_substitute_parameter_name_replaces_auto_name() -> None:
    edit = {"changes": {"file:///f.py": [{"range": {}, "newText": "def f(p): return p + 1"}]}}
    result = _substitute_introduced_parameter_name(edit, parameter_name="my_param")
    text = result["changes"]["file:///f.py"][0]["newText"]
    assert "my_param" in text
    assert " p " not in text or "my_param" in text  # either replaced or unchanged boundary


def test_substitute_parameter_name_empty_name_no_op() -> None:
    edit = {"changes": {"file:///f.py": [{"range": {}, "newText": "def f(p): pass"}]}}
    result = _substitute_introduced_parameter_name(edit, parameter_name="")
    assert result == edit


def test_substitute_parameter_name_non_dict_passthrough() -> None:
    result = _substitute_introduced_parameter_name("not a dict", parameter_name="x")  # type: ignore[arg-type]
    assert result == "not a dict"


def test_substitute_parameter_name_document_changes_shape() -> None:
    edit = {"documentChanges": [{
        "edits": [{"range": {}, "newText": "def f(param): return param"}],
    }]}
    result = _substitute_introduced_parameter_name(edit, parameter_name="my_arg")
    text = result["documentChanges"][0]["edits"][0]["newText"]
    assert "my_arg" in text


# ---------------------------------------------------------------------------
# _filter_definition_deletion_hunks
# ---------------------------------------------------------------------------


def test_filter_definition_deletion_non_dict_passthrough() -> None:
    result = _filter_definition_deletion_hunks("not a dict")  # type: ignore[arg-type]
    assert result == "not a dict"


def test_filter_definition_deletion_drops_multi_line_empty_newtext() -> None:
    edit = {"changes": {"file:///f.rs": [
        {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 5, "character": 0}}, "newText": ""},
        {"range": {"start": {"line": 10, "character": 0}, "end": {"line": 10, "character": 3}}, "newText": "new()"},
    ]}}
    result = _filter_definition_deletion_hunks(edit)
    remaining = result["changes"]["file:///f.rs"]
    assert len(remaining) == 1
    assert remaining[0]["newText"] == "new()"


def test_filter_definition_deletion_keeps_same_line_empty_newtext() -> None:
    edit = {"changes": {"file:///f.rs": [
        {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 5}}, "newText": ""},
    ]}}
    result = _filter_definition_deletion_hunks(edit)
    # Same-line empty newText is NOT a definition deletion hunk → kept
    assert len(result["changes"]["file:///f.rs"]) == 1


def test_filter_definition_deletion_document_changes_shape() -> None:
    edit = {"documentChanges": [{
        "edits": [
            {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 3, "character": 0}}, "newText": ""},
            {"range": {"start": {"line": 10, "character": 0}, "end": {"line": 10, "character": 0}}, "newText": "x"},
        ],
    }]}
    result = _filter_definition_deletion_hunks(edit)
    remaining_edits = result["documentChanges"][0]["edits"]
    assert len(remaining_edits) == 1
    assert remaining_edits[0]["newText"] == "x"


def test_filter_definition_deletion_unknown_key_passed_through() -> None:
    edit = {"someOtherKey": "value"}
    result = _filter_definition_deletion_hunks(edit)
    assert result["someOtherKey"] == "value"


# ---------------------------------------------------------------------------
# _capability_not_available_envelope
# ---------------------------------------------------------------------------


def test_capability_not_available_envelope_structure() -> None:
    envelope = _capability_not_available_envelope(language="rust", kind="refactor.extract.function")
    assert envelope["status"] == "skipped"
    assert envelope["language"] == "rust"
    assert envelope["kind"] == "refactor.extract.function"
    assert "lsp_does_not_support_refactor.extract.function" in str(envelope["reason"])


def test_capability_not_available_envelope_with_server_id() -> None:
    envelope = _capability_not_available_envelope(
        language="python", kind="source.organizeImports", server_id="ruff"
    )
    assert envelope["server_id"] == "ruff"


# ---------------------------------------------------------------------------
# _select_candidate_action (G1 disambiguation policy)
# ---------------------------------------------------------------------------


def _make_action(title: str, is_preferred: bool = False) -> Any:
    action = MagicMock()
    action.title = title
    action.is_preferred = is_preferred
    action.id = f"action_{title.replace(' ', '_')}"
    action.action_id = None
    action.provenance = "rust-analyzer"
    return action


def test_select_candidate_action_empty_list_returns_none_none() -> None:
    chosen, envelope = _select_candidate_action([], title_match=None)
    assert chosen is None
    assert envelope is None


def test_select_candidate_action_no_title_match_prefers_is_preferred() -> None:
    actions = [_make_action("Normal"), _make_action("Preferred", is_preferred=True)]
    chosen, envelope = _select_candidate_action(actions, title_match=None)
    assert envelope is None
    assert chosen.title == "Preferred"


def test_select_candidate_action_no_title_match_fallback_to_first() -> None:
    actions = [_make_action("First"), _make_action("Second")]
    chosen, envelope = _select_candidate_action(actions, title_match=None)
    assert envelope is None
    assert chosen.title == "First"


def test_select_candidate_action_title_match_exact_one_hit() -> None:
    actions = [_make_action("Extract Function"), _make_action("Extract Variable")]
    chosen, envelope = _select_candidate_action(actions, title_match="extract function")
    assert envelope is None
    assert chosen.title == "Extract Function"


def test_select_candidate_action_title_match_zero_hits_returns_envelope() -> None:
    actions = [_make_action("Extract Function")]
    chosen, envelope = _select_candidate_action(actions, title_match="inline")
    assert chosen is None
    assert envelope is not None
    assert envelope["status"] == "skipped"
    assert envelope["reason"] == "no_candidate_matched_title_match"


def test_select_candidate_action_title_match_multiple_hits_returns_envelope() -> None:
    actions = [_make_action("Change pub"), _make_action("Change pub(crate)")]
    chosen, envelope = _select_candidate_action(actions, title_match="pub")
    assert chosen is None
    assert envelope is not None
    assert envelope["reason"] == "multiple_candidates_matched_title_match"
    assert len(envelope["candidates"]) == 2


def test_select_candidate_action_title_match_case_insensitive() -> None:
    actions = [_make_action("EXTRACT FUNCTION")]
    chosen, envelope = _select_candidate_action(actions, title_match="extract function")
    assert envelope is None
    assert chosen.title == "EXTRACT FUNCTION"


# ---------------------------------------------------------------------------
# _dispatch_single_kind_facade
# ---------------------------------------------------------------------------


def _make_mock_coord_for_dispatch(
    *,
    supports: bool = True,
    actions: list | None = None,
) -> MagicMock:
    coord = MagicMock()
    coord.supports_kind.return_value = supports
    if actions is None:
        actions = []

    import asyncio

    async def _async_actions(**kw: Any) -> list:
        return actions

    coord.merge_code_actions.side_effect = lambda **kw: _async_actions(**kw)
    return coord


def test_dispatch_single_kind_facade_unknown_language(tmp_path: Path) -> None:
    result = _dispatch_single_kind_facade(
        stage_name="test_stage",
        file="file.java",
        position={"line": 0, "character": 0},
        kind="refactor.extract.function",
        project_root=tmp_path,
        dry_run=False,
        language=None,  # .java → "unknown"
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_dispatch_single_kind_facade_capability_not_available(tmp_path: Path) -> None:
    from serena.tools.facade_support import coordinator_for_facade
    mock_coord = _make_mock_coord_for_dispatch(supports=False)

    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
        result = _dispatch_single_kind_facade(
            stage_name="test_stage",
            file="file.rs",
            position={"line": 0, "character": 0},
            kind="refactor.extract.function",
            project_root=tmp_path,
            dry_run=False,
            language="rust",
        )

    payload = json.loads(result)
    assert payload["status"] == "skipped"


def test_dispatch_single_kind_facade_no_actions_returns_failure(tmp_path: Path) -> None:
    mock_coord = _make_mock_coord_for_dispatch(supports=True, actions=[])

    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
        result = _dispatch_single_kind_facade(
            stage_name="test_stage",
            file="file.rs",
            position={"line": 0, "character": 0},
            kind="refactor.extract.function",
            project_root=tmp_path,
            dry_run=False,
            language="rust",
        )

    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


def test_dispatch_single_kind_facade_dry_run_returns_preview_token(tmp_path: Path) -> None:
    action = _make_action("Extract Function")
    mock_coord = _make_mock_coord_for_dispatch(supports=True, actions=[action])

    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
        result = _dispatch_single_kind_facade(
            stage_name="test_stage",
            file="file.rs",
            position={"line": 0, "character": 0},
            kind="refactor.extract.function",
            project_root=tmp_path,
            dry_run=True,
            language="rust",
        )

    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["no_op"] is False
    assert payload["preview_token"] is not None


def test_dispatch_single_kind_facade_title_match_miss_envelope(tmp_path: Path) -> None:
    action = _make_action("Extract Function")
    mock_coord = _make_mock_coord_for_dispatch(supports=True, actions=[action])

    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
        result = _dispatch_single_kind_facade(
            stage_name="test_stage",
            file="file.rs",
            position={"line": 0, "character": 0},
            kind="refactor.extract.function",
            project_root=tmp_path,
            dry_run=False,
            language="rust",
            title_match="inline",  # miss
        )

    payload = json.loads(result)
    assert payload["status"] == "skipped"
    assert payload["reason"] == "no_candidate_matched_title_match"


def test_dispatch_single_kind_facade_apply_success(tmp_path: Path) -> None:
    action = _make_action("Extract Function")
    mock_coord = _make_mock_coord_for_dispatch(supports=True, actions=[action])

    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
        with patch(
            "serena.tools.scalpel_facades.apply_action_and_checkpoint",
            return_value=("ckpt-xyz", {"changes": {"file:///x.rs": []}}),
        ):
            result = _dispatch_single_kind_facade(
                stage_name="test_stage",
                file="file.rs",
                position={"line": 0, "character": 0},
                kind="refactor.extract.function",
                project_root=tmp_path,
                dry_run=False,
                language="rust",
            )

    payload = json.loads(result)
    assert payload["applied"] is True
    assert payload["checkpoint_id"] == "ckpt-xyz"


# ---------------------------------------------------------------------------
# SplitFileTool.apply — validation paths
# ---------------------------------------------------------------------------


def _make_split_file_tool(project_root: str) -> SplitFileTool:
    tool = object.__new__(SplitFileTool)
    tool.get_project_root = lambda: project_root  # type: ignore[method-assign]
    return tool


def test_split_file_workspace_boundary_violation(tmp_path: Path) -> None:
    other = Path(tempfile.mkdtemp())
    try:
        tool = _make_split_file_tool(str(tmp_path))
        result = tool.apply(
            file=str(other / "intruder.py"),
            groups={"target": ["MyClass"]},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_split_file_empty_groups_returns_no_op(tmp_path: Path) -> None:
    tool = _make_split_file_tool(str(tmp_path))
    f = tmp_path / "main.py"
    f.write_text("pass")
    result = tool.apply(
        file=str(f),
        groups={},
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload.get("no_op") is True


def test_split_file_unknown_language_returns_failure(tmp_path: Path) -> None:
    tool = _make_split_file_tool(str(tmp_path))
    f = tmp_path / "main.java"
    f.write_text("public class Main {}")
    result = tool.apply(
        file=str(f),
        groups={"target": ["Main"]},
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"
    assert "Cannot infer language" in payload["failure"]["reason"]


# ---------------------------------------------------------------------------
# ExtractTool.apply — validation paths
# ---------------------------------------------------------------------------


def _make_extract_tool(project_root: str) -> ExtractTool:
    tool = object.__new__(ExtractTool)
    tool.get_project_root = lambda: project_root  # type: ignore[method-assign]
    return tool


def test_extract_no_range_no_name_path_returns_failure(tmp_path: Path) -> None:
    tool = _make_extract_tool(str(tmp_path))
    f = tmp_path / "main.rs"
    f.write_text("fn foo() { let x = 1; }")
    result = tool.apply(
        file=str(f),
        range=None,
        name_path=None,
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"
    assert "range= or name_path=" in payload["failure"]["reason"]


def test_extract_unknown_target_returns_failure(tmp_path: Path) -> None:
    tool = _make_extract_tool(str(tmp_path))
    f = tmp_path / "main.rs"
    f.write_text("fn foo() { let x = 1; }")
    result = tool.apply(
        file=str(f),
        range={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
        target="nonexistent_target",  # type: ignore[arg-type]
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_extract_unknown_language_returns_failure(tmp_path: Path) -> None:
    tool = _make_extract_tool(str(tmp_path))
    f = tmp_path / "main.go"
    f.write_text("package main")
    result = tool.apply(
        file=str(f),
        range={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
        target="function",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"
    assert "Cannot infer language" in payload["failure"]["reason"]


def test_extract_invalid_target_for_language_returns_not_available(tmp_path: Path) -> None:
    """Python does not support target='static' — should return CAPABILITY_NOT_AVAILABLE envelope."""
    tool = _make_extract_tool(str(tmp_path))
    f = tmp_path / "main.py"
    f.write_text("def foo(): pass")
    result = tool.apply(
        file=str(f),
        range={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
        target="static",  # not valid for python
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    # The envelope is the _capability_not_available_envelope shape
    assert payload["status"] == "skipped"
    assert payload["language"] == "python"


def test_extract_java_invalid_target_module_returns_not_available(tmp_path: Path) -> None:
    """Java does not support target='module'."""
    tool = _make_extract_tool(str(tmp_path))
    f = tmp_path / "Main.java"
    f.write_text("public class Main {}")
    result = tool.apply(
        file=str(f),
        range={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
        target="module",  # not valid for java
        language="java",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["status"] == "skipped"
    assert payload["language"] == "java"


def test_extract_workspace_boundary_violation(tmp_path: Path) -> None:
    other = Path(tempfile.mkdtemp())
    try:
        tool = _make_extract_tool(str(tmp_path))
        result = tool.apply(
            file=str(other / "intruder.rs"),
            range={"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_extract_valid_targets_matrix_completeness() -> None:
    """Verify the valid-targets matrix has the right languages and each has at least one target."""
    assert "rust" in _EXTRACT_VALID_TARGETS_BY_LANGUAGE
    assert "python" in _EXTRACT_VALID_TARGETS_BY_LANGUAGE
    assert "java" in _EXTRACT_VALID_TARGETS_BY_LANGUAGE
    for lang, targets in _EXTRACT_VALID_TARGETS_BY_LANGUAGE.items():
        assert len(targets) > 0, f"{lang} has empty target set"


# ---------------------------------------------------------------------------
# ConvertModuleLayoutTool.apply — validation paths
# ---------------------------------------------------------------------------


def _make_convert_module_tool(project_root: str) -> ConvertModuleLayoutTool:
    tool = object.__new__(ConvertModuleLayoutTool)
    tool.get_project_root = lambda: project_root  # type: ignore[method-assign]
    return tool


def test_convert_module_layout_invalid_target_layout(tmp_path: Path) -> None:
    tool = _make_convert_module_tool(str(tmp_path))
    f = tmp_path / "main.rs"
    f.write_text("mod foo;")
    result = tool.apply(
        file=str(f),
        position={"line": 0, "character": 0},
        target_layout="invalid_layout",  # type: ignore[arg-type]
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"
    assert "target_layout" in payload["failure"]["reason"]


def test_convert_module_layout_workspace_boundary_violation(tmp_path: Path) -> None:
    other = Path(tempfile.mkdtemp())
    try:
        tool = _make_convert_module_tool(str(tmp_path))
        result = tool.apply(
            file=str(other / "intruder.rs"),
            position={"line": 0, "character": 0},
            target_layout="file",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_convert_module_layout_valid_dispatches_to_single_kind(tmp_path: Path) -> None:
    tool = _make_convert_module_tool(str(tmp_path))
    f = tmp_path / "main.rs"
    f.write_text("mod foo;")

    mock_coord = _make_mock_coord_for_dispatch(supports=False)  # gate fails → skipped envelope

    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
        result = tool.apply(
            file=str(f),
            position={"line": 0, "character": 0},
            target_layout="file",
            allow_out_of_workspace=True,
        )

    payload = json.loads(result)
    assert payload["status"] == "skipped"


# ---------------------------------------------------------------------------
# ExtractTool — target-kind mapping (static table tests)
# ---------------------------------------------------------------------------


def test_extract_target_to_kind_all_entries_have_known_kind() -> None:
    for target, kind in _EXTRACT_TARGET_TO_KIND.items():
        assert kind.startswith("refactor."), f"{target!r} → {kind!r} doesn't start with refactor."


# ---------------------------------------------------------------------------
# Async helper: _run_async edge case (exception from coro)
# ---------------------------------------------------------------------------


def test_run_async_propagates_exception_from_coro() -> None:
    from serena.tools.scalpel_facades import _run_async

    async def _raises() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        _run_async(_raises())
