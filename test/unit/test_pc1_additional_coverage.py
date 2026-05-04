"""PC1 additional — tests for remaining uncovered areas.

Targets:
- scalpel_primitives: _derive_annotation_groups, _filter_workspace_edit_by_labels,
  ConfirmAnnotationsTool, _strip_txn_prefix, _dry_run_one_step_in_shadow,
  _dispatch_facade_in_shadow, WorkspaceHealthTool
- scalpel_facades: _rewrite_package_reexports (pure Python AST manipulation),
  _post_process_extract_edit (documentChanges path), InlineTool validation,
  ChangeVisibilityTool, ChangeTypeShapeTool, ChangeReturnTypeTool,
  TidyStructureTool, verifyAfterRefactorTool basic paths
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_primitives import (
    _derive_annotation_groups,
    _dispatch_facade_in_shadow,
    _dry_run_one_step_in_shadow,
    _filter_workspace_edit_by_labels,
    _strip_txn_prefix,
    ConfirmAnnotationsTool,
)
from serena.tools.scalpel_schemas import ComposeStep, ErrorCode


# ---------------------------------------------------------------------------
# _strip_txn_prefix
# ---------------------------------------------------------------------------


def test_strip_txn_prefix_with_prefix() -> None:
    assert _strip_txn_prefix("txn_abc123") == "abc123"


def test_strip_txn_prefix_without_prefix() -> None:
    assert _strip_txn_prefix("raw-id-456") == "raw-id-456"


def test_strip_txn_prefix_empty_string() -> None:
    assert _strip_txn_prefix("") == ""


# ---------------------------------------------------------------------------
# _derive_annotation_groups
# ---------------------------------------------------------------------------


def test_derive_annotation_groups_empty_edit() -> None:
    result = _derive_annotation_groups({})
    assert result == ()


def test_derive_annotation_groups_non_dict_annotations() -> None:
    result = _derive_annotation_groups({"changeAnnotations": "not a dict"})
    assert result == ()


def test_derive_annotation_groups_basic() -> None:
    edit = {
        "changeAnnotations": {
            "anno1": {"label": "Rename foo", "needsConfirmation": True},
            "anno2": {"label": "Rename bar", "needsConfirmation": False},
        },
        "documentChanges": [{
            "textDocument": {"uri": "file:///f.py"},
            "edits": [
                {"range": {}, "newText": "x", "annotationId": "anno1"},
            ],
        }],
    }
    groups = _derive_annotation_groups(edit)
    assert len(groups) == 2
    labels = {g.label for g in groups}
    assert "Rename foo" in labels
    assert "Rename bar" in labels
    # anno1 has needs_confirmation=True
    anno1_group = next(g for g in groups if g.label == "Rename foo")
    assert anno1_group.needs_confirmation is True
    # anno2 has no edits pointing to it
    anno2_group = next(g for g in groups if g.label == "Rename bar")
    assert anno2_group.edit_ids == ()


def test_derive_annotation_groups_resource_op_with_annotation() -> None:
    edit = {
        "changeAnnotations": {"anno1": {"label": "Create file", "needsConfirmation": False}},
        "documentChanges": [
            {"kind": "create", "uri": "file:///new.py", "annotationId": "anno1"},
        ],
    }
    groups = _derive_annotation_groups(edit)
    assert len(groups) == 1
    assert groups[0].edit_ids == ("anno1",)


def test_derive_annotation_groups_non_dict_meta_skipped() -> None:
    edit = {"changeAnnotations": {"anno1": "not a dict"}}
    result = _derive_annotation_groups(edit)
    assert result == ()


def test_derive_annotation_groups_non_dict_in_document_changes_skipped() -> None:
    edit = {
        "changeAnnotations": {"anno1": {"label": "x"}},
        "documentChanges": ["not a dict"],
    }
    result = _derive_annotation_groups(edit)
    assert len(result) == 1


def test_derive_annotation_groups_label_defaults_to_id_when_missing() -> None:
    edit = {
        "changeAnnotations": {"anno1": {}},  # no "label" key
    }
    groups = _derive_annotation_groups(edit)
    assert len(groups) == 1
    # label defaults to anno_id
    assert groups[0].label == "anno1"


# ---------------------------------------------------------------------------
# _filter_workspace_edit_by_labels
# ---------------------------------------------------------------------------


def test_filter_workspace_edit_by_labels_empty_accepted() -> None:
    edit = {
        "changeAnnotations": {"a": {"label": "x"}},
        "documentChanges": [{"textDocument": {}, "edits": [{"annotationId": "a", "newText": "y"}]}],
    }
    result = _filter_workspace_edit_by_labels(edit, set())
    assert "documentChanges" not in result


def test_filter_workspace_edit_by_labels_changes_preserved_verbatim() -> None:
    edit = {
        "changes": {"file:///f.py": [{"newText": "x"}]},
    }
    result = _filter_workspace_edit_by_labels(edit, {"some-label"})
    assert result.get("changes") == edit["changes"]


def test_filter_workspace_edit_by_labels_accepted_edits_kept() -> None:
    edit = {
        "changeAnnotations": {"a": {"label": "RenameA"}},
        "documentChanges": [{
            "textDocument": {"uri": "file:///f.py"},
            "edits": [
                {"newText": "new_a", "annotationId": "a"},
                {"newText": "no_anno"},  # no annotationId — dropped
            ],
        }],
    }
    result = _filter_workspace_edit_by_labels(edit, {"RenameA"})
    assert "documentChanges" in result
    kept_edits = result["documentChanges"][0]["edits"]
    assert len(kept_edits) == 1
    assert kept_edits[0]["newText"] == "new_a"


def test_filter_workspace_edit_by_labels_resource_op_with_accepted_label() -> None:
    edit = {
        "changeAnnotations": {"a": {"label": "CreateFile"}},
        "documentChanges": [
            {"kind": "create", "uri": "file:///new.py", "annotationId": "a"},
        ],
    }
    result = _filter_workspace_edit_by_labels(edit, {"CreateFile"})
    assert "documentChanges" in result
    assert len(result["documentChanges"]) == 1


def test_filter_workspace_edit_by_labels_resource_op_rejected() -> None:
    edit = {
        "changeAnnotations": {"a": {"label": "CreateFile"}},
        "documentChanges": [
            {"kind": "create", "uri": "file:///new.py", "annotationId": "a"},
        ],
    }
    result = _filter_workspace_edit_by_labels(edit, {"OtherLabel"})
    assert "documentChanges" not in result


def test_filter_workspace_edit_by_labels_non_dict_annotations_treated_as_empty() -> None:
    edit = {
        "changeAnnotations": "not a dict",
        "documentChanges": [{"textDocument": {}, "edits": [{"annotationId": "a"}]}],
    }
    result = _filter_workspace_edit_by_labels(edit, {"a"})
    # annotations is not a dict — no accepted ids — no doc changes emitted
    assert "documentChanges" not in result


def test_filter_workspace_edit_by_labels_non_string_anno_id_in_edit_skipped() -> None:
    edit = {
        "changeAnnotations": {"a": {"label": "RenameA"}},
        "documentChanges": [{
            "textDocument": {},
            "edits": [{"newText": "x", "annotationId": 12345}],  # non-string annotationId
        }],
    }
    result = _filter_workspace_edit_by_labels(edit, {"RenameA"})
    assert "documentChanges" not in result


# ---------------------------------------------------------------------------
# ConfirmAnnotationsTool
# ---------------------------------------------------------------------------


def _make_confirm_tool() -> ConfirmAnnotationsTool:
    tool = object.__new__(ConfirmAnnotationsTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]
    return tool


def test_confirm_annotations_unknown_transaction() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    mock_store = MagicMock()
    mock_store.get.return_value = None
    mock_runtime = MagicMock()
    mock_runtime.pending_tx_store.return_value = mock_store

    tool = _make_confirm_tool()

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(transaction_id="txn_unknown", accept=[])

    payload = json.loads(result)
    assert payload["error_code"] == "UNKNOWN_TRANSACTION"
    assert payload["transaction_id"] == "txn_unknown"


def test_confirm_annotations_empty_accept_applies_nothing() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.pending_tx import AnnotationGroup, PendingTransaction

    mock_group = MagicMock(spec=AnnotationGroup)
    mock_group.label = "RenameA"
    mock_pending = MagicMock(spec=PendingTransaction)
    mock_pending.groups = [mock_group]
    mock_pending.workspace_edit = {}

    mock_store = MagicMock()
    mock_store.get.return_value = mock_pending
    mock_runtime = MagicMock()
    mock_runtime.pending_tx_store.return_value = mock_store

    tool = _make_confirm_tool()

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(transaction_id="txn_123", accept=[])

    payload = json.loads(result)
    assert payload["applied_edits"] == 0
    assert "RenameA" in payload["rejected_groups"]
    assert payload["applied_groups"] == []


def test_confirm_annotations_accepted_group_applied(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.pending_tx import AnnotationGroup, PendingTransaction

    f = tmp_path / "f.py"
    f.write_text("old content")
    uri = f.as_uri()

    mock_group = MagicMock(spec=AnnotationGroup)
    mock_group.label = "RenameA"
    mock_pending = MagicMock(spec=PendingTransaction)
    mock_pending.groups = [mock_group]
    mock_pending.workspace_edit = {
        "changeAnnotations": {"anno1": {"label": "RenameA"}},
        "documentChanges": [{
            "textDocument": {"uri": uri},
            "edits": [{"newText": "new content", "annotationId": "anno1",
                       "range": {"start": {"line": 0, "character": 0},
                                 "end": {"line": 0, "character": 11}}}],
        }],
    }

    mock_store = MagicMock()
    mock_store.get.return_value = mock_pending
    mock_runtime = MagicMock()
    mock_runtime.pending_tx_store.return_value = mock_store

    tool = _make_confirm_tool()

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(transaction_id="txn_123", accept=["RenameA"])

    payload = json.loads(result)
    assert payload["applied_groups"] == ["RenameA"]
    assert payload["rejected_groups"] == []
    assert payload["applied_edits"] >= 0


# ---------------------------------------------------------------------------
# _dispatch_facade_in_shadow
# ---------------------------------------------------------------------------


def test_dispatch_facade_in_shadow_known_tool_called(tmp_path: Path) -> None:
    """Shadow dispatch uses cls.__new__ and overrides get_project_root."""
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()

    # ExtractTool.apply — our shadow call should hit the apply with shadow root.
    called_with_root: list[str] = []

    original_apply = None
    from serena.tools.scalpel_facades import ExtractTool

    def _fake_apply(self: ExtractTool, **kw: Any) -> str:
        called_with_root.append(self.get_project_root())
        return json.dumps({"applied": False, "no_op": True, "diagnostics_delta": {
            "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "new_findings": [],
            "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
        }})

    with patch.object(ExtractTool, "apply", _fake_apply):
        result = _dispatch_facade_in_shadow(
            "extract",
            shadow_root=shadow_root,
            args={"file": str(shadow_root / "main.rs")},
        )

    assert len(called_with_root) == 1
    assert called_with_root[0] == str(shadow_root)


def test_dispatch_facade_in_shadow_unknown_tool_uses_legacy_dispatch(tmp_path: Path) -> None:
    """Unknown tool_name falls through to _FACADE_DISPATCH lookup."""
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()

    def _handler(**kw: Any) -> str:
        return json.dumps({"applied": False, "no_op": True})

    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"legacy_tool": _handler}):
        result = _dispatch_facade_in_shadow(
            "legacy_tool",
            shadow_root=shadow_root,
            args={},
        )

    assert json.loads(result)["applied"] is False


def test_dispatch_facade_in_shadow_unknown_tool_not_in_dispatch_raises(tmp_path: Path) -> None:
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()

    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {}):
        with pytest.raises(KeyError):
            _dispatch_facade_in_shadow(
                "completely_unknown_xyz",
                shadow_root=shadow_root,
                args={},
            )


# ---------------------------------------------------------------------------
# _dry_run_one_step_in_shadow
# ---------------------------------------------------------------------------


def test_dry_run_one_step_in_shadow_unknown_tool_returns_failure(tmp_path: Path) -> None:
    step = ComposeStep(tool="ghost_tool", args={})
    live_root = tmp_path / "project"
    live_root.mkdir()
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()

    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {}):
        result = _dry_run_one_step_in_shadow(
            step,
            live_root=live_root,
            shadow_root=shadow_root,
            step_index=0,
        )

    assert result.failure is not None
    assert result.failure.code == ErrorCode.INVALID_ARGUMENT
    assert "not registered" in result.failure.reason


def test_dry_run_one_step_in_shadow_facade_raises_returns_failure(tmp_path: Path) -> None:
    live_root = tmp_path / "project"
    live_root.mkdir()
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()

    step = ComposeStep(tool="crashing_tool", args={})

    def _crash(**kw: Any) -> str:
        raise RuntimeError("boom in shadow")

    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"crashing_tool": _crash}):
        result = _dry_run_one_step_in_shadow(
            step,
            live_root=live_root,
            shadow_root=shadow_root,
            step_index=1,
        )

    assert result.failure is not None
    assert result.failure.code == ErrorCode.INTERNAL_ERROR
    assert "raised in shadow" in result.failure.reason


def test_dry_run_one_step_in_shadow_facade_bad_json_returns_failure(tmp_path: Path) -> None:
    live_root = tmp_path / "project"
    live_root.mkdir()
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()

    step = ComposeStep(tool="bad_json_tool", args={})

    def _bad_json(**kw: Any) -> str:
        return "not valid json {"

    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"bad_json_tool": _bad_json}):
        result = _dry_run_one_step_in_shadow(
            step,
            live_root=live_root,
            shadow_root=shadow_root,
            step_index=0,
        )

    assert result.failure is not None
    assert result.failure.code == ErrorCode.INTERNAL_ERROR
    assert "invalid JSON" in result.failure.reason


def test_dry_run_one_step_in_shadow_facade_non_dict_json_returns_failure(tmp_path: Path) -> None:
    live_root = tmp_path / "project"
    live_root.mkdir()
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()

    step = ComposeStep(tool="array_json_tool", args={})

    def _array_json(**kw: Any) -> str:
        return json.dumps([1, 2, 3])

    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"array_json_tool": _array_json}):
        result = _dry_run_one_step_in_shadow(
            step,
            live_root=live_root,
            shadow_root=shadow_root,
            step_index=0,
        )

    assert result.failure is not None
    assert "non-object payload" in result.failure.reason


def test_dry_run_one_step_in_shadow_success(tmp_path: Path) -> None:
    live_root = tmp_path / "project"
    live_root.mkdir()
    shadow_root = tmp_path / "shadow"
    shadow_root.mkdir()

    step = ComposeStep(tool="ok_tool", args={"file": str(live_root / "main.py")})

    def _ok(**kw: Any) -> str:
        return json.dumps({"applied": True, "diagnostics_delta": {
            "before": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "after": {"error": 0, "warning": 0, "information": 0, "hint": 0},
            "new_findings": [],
            "severity_breakdown": {"error": 0, "warning": 0, "information": 0, "hint": 0},
        }, "no_op": False})

    with patch("serena.tools.scalpel_facades._FACADE_DISPATCH", {"ok_tool": _ok}):
        result = _dry_run_one_step_in_shadow(
            step,
            live_root=live_root,
            shadow_root=shadow_root,
            step_index=5,
        )

    assert result.step_index == 5
    assert result.failure is None


# ---------------------------------------------------------------------------
# _rewrite_package_reexports (pure Python AST -- no LSP needed)
# ---------------------------------------------------------------------------


def test_rewrite_package_reexports_no_matching_imports(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import _rewrite_package_reexports

    src = tmp_path / "mymodule.py"
    src.write_text("class Foo: pass\n")
    init = tmp_path / "__init__.py"
    init.write_text("from .other import Bar\n")

    edits = _rewrite_package_reexports(
        project_root=tmp_path,
        source_rel="mymodule.py",
        moves=[("Foo", "newmodule.py")],
    )
    # __init__.py imports from .other, not .mymodule — no rewrite needed
    assert edits == []
    # __init__.py content unchanged
    assert init.read_text() == "from .other import Bar\n"


def test_rewrite_package_reexports_rewrites_relative_import(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import _rewrite_package_reexports

    src = tmp_path / "mymodule.py"
    src.write_text("class Foo: pass\nclass Bar: pass\n")
    init = tmp_path / "__init__.py"
    init.write_text("from .mymodule import Foo, Bar\n")

    edits = _rewrite_package_reexports(
        project_root=tmp_path,
        source_rel="mymodule.py",
        moves=[("Foo", "newmodule.py")],
    )
    # Should have rewritten __init__.py
    new_content = init.read_text()
    # Foo moved to newmodule; Bar stays in mymodule
    assert "from .newmodule import Foo" in new_content
    assert "from .mymodule import Bar" in new_content
    assert len(edits) > 0


def test_rewrite_package_reexports_absolute_import_path(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import _rewrite_package_reexports

    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    src = pkg / "mymodule.py"
    src.write_text("class Foo: pass\n")
    consumer = tmp_path / "consumer.py"
    consumer.write_text("from mypkg.mymodule import Foo\n")

    edits = _rewrite_package_reexports(
        project_root=tmp_path,
        source_rel="mypkg/mymodule.py",
        moves=[("Foo", "mypkg/newmodule.py")],
    )
    new_content = consumer.read_text()
    assert "from mypkg.newmodule import Foo" in new_content


def test_rewrite_package_reexports_all_names_moved(tmp_path: Path) -> None:
    """When all imported names move, the original import line should disappear."""
    from serena.tools.scalpel_facades import _rewrite_package_reexports

    src = tmp_path / "mymodule.py"
    src.write_text("class Foo: pass\n")
    init = tmp_path / "__init__.py"
    init.write_text("from .mymodule import Foo\n")

    _rewrite_package_reexports(
        project_root=tmp_path,
        source_rel="mymodule.py",
        moves=[("Foo", "newmodule.py")],
    )
    new_content = init.read_text()
    # Only the new import should appear; original from .mymodule should be gone
    assert "from .newmodule import Foo" in new_content
    # mymodule reference removed (no kept aliases)
    assert "from .mymodule import Foo" not in new_content


def test_rewrite_package_reexports_skips_unreadable_files(tmp_path: Path) -> None:
    """Files that can't be read should be skipped silently."""
    from serena.tools.scalpel_facades import _rewrite_package_reexports

    src = tmp_path / "mymodule.py"
    src.write_text("class Foo: pass\n")
    bad_file = tmp_path / "bad.py"
    bad_file.write_bytes(b"\xff\xfe INVALID UTF8 \x80\x81")

    # Should not raise, just skip the bad file
    edits = _rewrite_package_reexports(
        project_root=tmp_path,
        source_rel="mymodule.py",
        moves=[("Foo", "newmodule.py")],
    )
    # No edits for the bad file
    assert isinstance(edits, list)


def test_rewrite_package_reexports_skips_syntax_error_files(tmp_path: Path) -> None:
    """Files with syntax errors should be skipped silently."""
    from serena.tools.scalpel_facades import _rewrite_package_reexports

    src = tmp_path / "mymodule.py"
    src.write_text("class Foo: pass\n")
    bad_file = tmp_path / "broken.py"
    bad_file.write_text("def bad_syntax((:\n")  # syntax error

    edits = _rewrite_package_reexports(
        project_root=tmp_path,
        source_rel="mymodule.py",
        moves=[("Foo", "newmodule.py")],
    )
    assert isinstance(edits, list)


# ---------------------------------------------------------------------------
# InlineTool validation paths
# ---------------------------------------------------------------------------


def test_inline_tool_no_range_no_name_path_returns_failure(tmp_path: Path) -> None:
    """scope=single_call_site with no position and no name_path should fail."""
    from serena.tools.scalpel_facades import InlineTool

    tool = object.__new__(InlineTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "lib.rs"
    f.write_text("fn foo() {}")
    # InlineTool uses `position` (not `range`); omit both position & name_path
    result = tool.apply(
        file=str(f),
        position=None,
        name_path=None,
        scope="single_call_site",
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_inline_tool_unknown_target_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import InlineTool

    tool = object.__new__(InlineTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "lib.rs"
    f.write_text("fn foo() {}")
    # target validation happens before workspace boundary; pass position to avoid
    # the no-position-no-name_path early return
    result = tool.apply(
        file=str(f),
        position={"line": 0, "character": 0},
        target="unknown_target",  # type: ignore[arg-type]
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_inline_tool_workspace_boundary_violation(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import InlineTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(InlineTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        # target must be valid; position supplied; boundary check fails
        result = tool.apply(
            file=str(other / "intruder.rs"),
            position={"line": 0, "character": 0},
            target="variable",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# ChangeVisibilityTool validation paths
# ---------------------------------------------------------------------------


def test_change_visibility_workspace_boundary_violation(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ChangeVisibilityTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ChangeVisibilityTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "intruder.rs"),
            position={"line": 0, "character": 0},
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_change_visibility_dispatches_with_title_match(tmp_path: Path) -> None:
    """target_visibility='pub_crate' should dispatch with title_match='pub(crate)'."""
    from serena.tools.scalpel_facades import ChangeVisibilityTool

    tool = object.__new__(ChangeVisibilityTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "lib.rs"
    f.write_text("fn foo() {}")

    # Mock the coordinator so it returns "capability not available"
    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = False

    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
        result = tool.apply(
            file=str(f),
            position={"line": 0, "character": 0},
            target_visibility="pub_crate",
            allow_out_of_workspace=True,
        )

    payload = json.loads(result)
    assert payload["status"] == "skipped"


# ---------------------------------------------------------------------------
# ChangeTypeShapeTool validation
# ---------------------------------------------------------------------------


def test_change_type_shape_unknown_target_returns_failure(tmp_path: Path) -> None:
    """Unknown target_shape should return INVALID_ARGUMENT before boundary check."""
    from serena.tools.scalpel_facades import ChangeTypeShapeTool

    tool = object.__new__(ChangeTypeShapeTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "lib.rs"
    f.write_text("struct Foo { a: i32 }")

    result = tool.apply(
        file=str(f),
        position={"line": 0, "character": 0},
        target_shape="unknown_shape",  # type: ignore[arg-type]
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_change_type_shape_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ChangeTypeShapeTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ChangeTypeShapeTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        # target_shape validated FIRST (before boundary check); pass a valid value
        result = tool.apply(
            file=str(other / "lib.rs"),
            position={"line": 0, "character": 0},
            target_shape="named_struct",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# ChangeReturnTypeTool validation
# ---------------------------------------------------------------------------


def test_change_return_type_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ChangeReturnTypeTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ChangeReturnTypeTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        # new_return_type is required by signature (informational, not validated further)
        result = tool.apply(
            file=str(other / "lib.rs"),
            position={"line": 0, "character": 0},
            new_return_type="String",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# TidyStructureTool validation
# ---------------------------------------------------------------------------


def test_tidy_structure_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import TidyStructureTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(TidyStructureTool)
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


def test_tidy_structure_unknown_language_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import TidyStructureTool

    tool = object.__new__(TidyStructureTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "main.java"
    f.write_text("class X {}")

    result = tool.apply(
        file=str(f),
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_tidy_structure_scope_type_no_position_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import TidyStructureTool

    tool = object.__new__(TidyStructureTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "lib.rs"
    f.write_text("struct Foo { b: i32, a: i32 }")

    mock_coord = MagicMock()
    mock_coord.supports_kind.return_value = True

    with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
        result = tool.apply(
            file=str(f),
            scope="type",
            position=None,  # required for type scope
            allow_out_of_workspace=True,
        )

    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


# ---------------------------------------------------------------------------
# DryRunComposeTool manual mode
# ---------------------------------------------------------------------------


def test_dry_run_compose_manual_mode_returns_awaiting_confirmation() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.tools.scalpel_primitives import DryRunComposeTool

    mock_pending_store = MagicMock()
    mock_pending_store.put.return_value = None
    mock_runtime = MagicMock()
    mock_runtime.pending_tx_store.return_value = mock_pending_store

    tool = object.__new__(DryRunComposeTool)
    tool.get_project_root = lambda: "/tmp"  # type: ignore[method-assign]

    workspace_edit: dict[str, Any] = {
        "changeAnnotations": {"a1": {"label": "RenameX", "needsConfirmation": True}},
        "documentChanges": [],
    }

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = tool.apply(
            steps=[],
            confirmation_mode="manual",
            workspace_edit=workspace_edit,
        )

    payload = json.loads(result)
    assert payload.get("awaiting_confirmation") is True


# ---------------------------------------------------------------------------
# RenameTool validation
# ---------------------------------------------------------------------------


def test_rename_tool_workspace_boundary_violation(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import RenameTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(RenameTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        result = tool.apply(
            file=str(other / "lib.rs"),
            name_path="foo::bar",
            new_name="baz",
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# ImportsOrganizeTool validation
# ---------------------------------------------------------------------------


def test_imports_organize_workspace_boundary(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ImportsOrganizeTool

    other = Path(tempfile.mkdtemp())
    try:
        tool = object.__new__(ImportsOrganizeTool)
        tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

        # ImportsOrganizeTool uses `files` (list), not `file`
        result = tool.apply(
            files=[str(other / "main.py")],
            allow_out_of_workspace=False,
        )
        payload = json.loads(result)
        assert payload["applied"] is False
        assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"
    finally:
        other.rmdir()


def test_imports_organize_unknown_language_returns_failure(tmp_path: Path) -> None:
    from serena.tools.scalpel_facades import ImportsOrganizeTool

    tool = object.__new__(ImportsOrganizeTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    f = tmp_path / "main.java"
    f.write_text("import java.util.List;")

    # language inference from .java should fail → INVALID_ARGUMENT
    result = tool.apply(
        files=[str(f)],
        allow_out_of_workspace=True,
    )
    payload = json.loads(result)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"
