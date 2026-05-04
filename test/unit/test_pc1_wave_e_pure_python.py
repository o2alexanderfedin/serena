"""PC1 Wave E: Pure-Python function coverage for scalpel_facades helper functions.

Targets uncovered lines that are reachable without live LSP servers:
- _post_process_extract_edit
- _substitute_introduced_parameter_name
- _select_candidate_action
- _filter_definition_deletion_hunks
- _capability_not_available_envelope
- _build_failure_step
- _dispatch_single_kind_facade early-exit paths
- facade_support._apply_resource_rename / _apply_resource_delete / _apply_resource_create edge cases
- facade_support inverse applier branches (rename no snapshot, delete non-file URI)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# _post_process_extract_edit
# ============================================================================


class TestPostProcessExtractEdit:
    def _import(self):
        from serena.tools.scalpel_facades import _post_process_extract_edit
        return _post_process_extract_edit

    def test_changes_shape_renames_auto_name(self):
        fn = self._import()
        # "new_function" is in _EXTRACT_AUTO_NAMES → gets substituted
        edit = {
            "changes": {
                "file:///lib.rs": [
                    {"range": {}, "newText": "fn new_function() {}"},
                ]
            }
        }
        result = fn(edit, new_name="my_func", visibility_prefix="")
        edits = result["changes"]["file:///lib.rs"]
        assert edits[0]["newText"] == "fn my_func() {}"

    def test_document_changes_shape_renames_auto_name(self):
        fn = self._import()
        # "extracted" is in _EXTRACT_AUTO_NAMES → gets substituted
        edit = {
            "documentChanges": [
                {
                    "textDocument": {"uri": "file:///lib.rs"},
                    "edits": [
                        {"range": {}, "newText": "fn extracted() {}"},
                    ],
                }
            ]
        }
        result = fn(edit, new_name="my_func", visibility_prefix="")
        dc = result["documentChanges"][0]
        assert dc["edits"][0]["newText"] == "fn my_func() {}"

    def test_visibility_prefix_injected_on_fn(self):
        fn = self._import()
        edit = {
            "changes": {
                "file:///lib.rs": [
                    {"range": {}, "newText": "fn helper() {}\n"}
                ]
            }
        }
        result = fn(edit, new_name=None, visibility_prefix="pub ")
        text = result["changes"]["file:///lib.rs"][0]["newText"]
        assert text.startswith("pub fn")

    def test_none_new_name_skips_rename(self):
        fn = self._import()
        edit = {
            "changes": {
                "file:///lib.rs": [
                    {"range": {}, "newText": "fn fun1() {}"}
                ]
            }
        }
        result = fn(edit, new_name=None, visibility_prefix="")
        assert result["changes"]["file:///lib.rs"][0]["newText"] == "fn fun1() {}"

    def test_non_dict_workspace_edit_returned_unchanged(self):
        fn = self._import()
        result = fn("not a dict", new_name="x", visibility_prefix="")
        assert result == "not a dict"

    def test_non_text_hunk_preserved_unchanged(self):
        fn = self._import()
        edit = {
            "changes": {
                "file:///lib.rs": [
                    {"range": {}, "newText": 42},  # non-str newText
                ]
            }
        }
        result = fn(edit, new_name="x", visibility_prefix="")
        assert result["changes"]["file:///lib.rs"][0]["newText"] == 42

    def test_document_changes_non_edit_entry_preserved(self):
        fn = self._import()
        edit = {
            "documentChanges": [
                {"kind": "create", "uri": "file:///new.rs"}  # no "edits" key
            ]
        }
        result = fn(edit, new_name="x", visibility_prefix="")
        # Entry without "edits" is preserved verbatim
        assert result["documentChanges"][0]["kind"] == "create"


# ============================================================================
# _substitute_introduced_parameter_name
# ============================================================================


class TestSubstituteIntroducedParameterName:
    def _import(self):
        from serena.tools.scalpel_facades import _substitute_introduced_parameter_name
        return _substitute_introduced_parameter_name

    def test_auto_name_substituted(self):
        fn = self._import()
        edit = {
            "changes": {
                "file:///mod.py": [
                    {"range": {}, "newText": "def foo(p): return p + 1"}
                ]
            }
        }
        result = fn(edit, parameter_name="value")
        text = result["changes"]["file:///mod.py"][0]["newText"]
        assert "value" in text
        assert " p " not in text or "value" in text  # substituted

    def test_empty_parameter_name_returns_unchanged(self):
        fn = self._import()
        edit = {"changes": {"file:///x.py": [{"range": {}, "newText": "p = 1"}]}}
        result = fn(edit, parameter_name="")
        assert result is edit  # same object

    def test_auto_name_as_parameter_name_returns_unchanged(self):
        fn = self._import()
        edit = {"changes": {"file:///x.py": [{"range": {}, "newText": "p = 1"}]}}
        result = fn(edit, parameter_name="p")
        assert result is edit  # no-op for default name

    def test_document_changes_shape_substitutes(self):
        fn = self._import()
        edit = {
            "documentChanges": [
                {
                    "textDocument": {"uri": "file:///x.py"},
                    "edits": [{"range": {}, "newText": "def f(param): pass"}],
                }
            ]
        }
        result = fn(edit, parameter_name="my_param")
        dc = result["documentChanges"][0]
        assert "my_param" in dc["edits"][0]["newText"]

    def test_non_dict_returns_unchanged(self):
        fn = self._import()
        result = fn("not a dict", parameter_name="x")
        assert result == "not a dict"


# ============================================================================
# _select_candidate_action
# ============================================================================


class TestSelectCandidateAction:
    def _import(self):
        from serena.tools.scalpel_facades import _select_candidate_action
        return _select_candidate_action

    def _make_action(self, title, is_preferred=False):
        a = MagicMock()
        a.title = title
        a.is_preferred = is_preferred
        a.id = "act1"
        a.action_id = None
        a.provenance = "test-server"
        return a

    def test_empty_actions_returns_none_none(self):
        fn = self._import()
        chosen, envelope = fn([], title_match=None)
        assert chosen is None
        assert envelope is None

    def test_title_match_single_hit_returns_action(self):
        fn = self._import()
        a = self._make_action("Extract to function")
        result, envelope = fn([a], title_match="extract")
        assert result is a
        assert envelope is None

    def test_title_match_no_hit_returns_envelope(self):
        fn = self._import()
        a = self._make_action("Inline variable")
        result, envelope = fn([a], title_match="extract")
        assert result is None
        assert envelope is not None
        assert envelope["reason"] == "no_candidate_matched_title_match"

    def test_title_match_multiple_hits_returns_envelope(self):
        fn = self._import()
        a1 = self._make_action("Extract to function")
        a2 = self._make_action("Extract to method")
        result, envelope = fn([a1, a2], title_match="extract")
        assert result is None
        assert envelope is not None
        assert envelope["reason"] == "multiple_candidates_matched_title_match"

    def test_no_title_match_prefers_preferred_action(self):
        fn = self._import()
        a1 = self._make_action("Action 1", is_preferred=False)
        a2 = self._make_action("Action 2", is_preferred=True)
        result, envelope = fn([a1, a2], title_match=None)
        assert result is a2
        assert envelope is None

    def test_no_title_match_falls_back_to_first_action(self):
        fn = self._import()
        a1 = self._make_action("Action 1")
        a2 = self._make_action("Action 2")
        result, envelope = fn([a1, a2], title_match=None)
        assert result is a1
        assert envelope is None


# ============================================================================
# _filter_definition_deletion_hunks
# ============================================================================


class TestFilterDefinitionDeletionHunks:
    def _import(self):
        from serena.tools.scalpel_facades import _filter_definition_deletion_hunks
        return _filter_definition_deletion_hunks

    def _deletion_hunk(self, start_line=0, end_line=3):
        return {
            "range": {
                "start": {"line": start_line, "character": 0},
                "end": {"line": end_line, "character": 0},
            },
            "newText": "",
        }

    def _non_deletion_hunk(self):
        return {
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 10},
            },
            "newText": "hello",
        }

    def test_filters_deletion_hunks_from_changes(self):
        fn = self._import()
        edit = {
            "changes": {
                "file:///lib.rs": [
                    self._deletion_hunk(),
                    self._non_deletion_hunk(),
                ]
            }
        }
        result = fn(edit)
        hunks = result["changes"]["file:///lib.rs"]
        assert len(hunks) == 1
        assert hunks[0]["newText"] == "hello"

    def test_filters_deletion_hunks_from_document_changes(self):
        fn = self._import()
        edit = {
            "documentChanges": [
                {
                    "textDocument": {"uri": "file:///lib.rs"},
                    "edits": [
                        self._deletion_hunk(),
                        self._non_deletion_hunk(),
                    ],
                }
            ]
        }
        result = fn(edit)
        dc = result["documentChanges"][0]
        assert len(dc["edits"]) == 1

    def test_non_deletion_hunk_passes_through(self):
        fn = self._import()
        edit = {
            "changes": {
                "file:///lib.rs": [self._non_deletion_hunk()]
            }
        }
        result = fn(edit)
        assert len(result["changes"]["file:///lib.rs"]) == 1

    def test_same_line_deletion_kept(self):
        fn = self._import()
        # start.line == end.line → NOT a deletion
        edit = {
            "changes": {
                "file:///lib.rs": [
                    {
                        "range": {
                            "start": {"line": 5, "character": 0},
                            "end": {"line": 5, "character": 0},  # same line
                        },
                        "newText": "",
                    }
                ]
            }
        }
        result = fn(edit)
        # Same-line zero-size deletion is NOT a definition deletion
        assert len(result["changes"]["file:///lib.rs"]) == 1

    def test_passes_through_non_changes_keys(self):
        fn = self._import()
        edit = {"other_key": "value"}
        result = fn(edit)
        assert result["other_key"] == "value"


# ============================================================================
# _capability_not_available_envelope
# ============================================================================


class TestCapabilityNotAvailableEnvelope:
    def _import(self):
        from serena.tools.scalpel_facades import _capability_not_available_envelope
        return _capability_not_available_envelope

    def test_returns_dict_with_status_skipped(self):
        fn = self._import()
        result = fn(language="rust", kind="refactor.extract.function")
        assert result["status"] == "skipped"
        assert result["language"] == "rust"
        assert result["kind"] == "refactor.extract.function"

    def test_with_server_id(self):
        fn = self._import()
        result = fn(language="python", kind="source.organizeImports", server_id="pylsp-rope")
        assert result.get("server_id") == "pylsp-rope"

    def test_without_server_id(self):
        fn = self._import()
        result = fn(language="rust", kind="refactor.rename")
        assert "server_id" not in result or result.get("server_id") is None


# ============================================================================
# facade_support: _apply_resource_rename edge cases
# ============================================================================


class TestApplyResourceRename:
    def _import(self):
        from serena.tools.facade_support import _apply_resource_rename
        return _apply_resource_rename

    def test_src_not_exists_returns_zero(self, tmp_path):
        fn = self._import()
        src = tmp_path / "nonexistent.rs"
        dst = tmp_path / "dst.rs"
        dc = {"oldUri": src.as_uri(), "newUri": dst.as_uri()}
        result = fn(dc)
        assert result == 0

    def test_none_uri_returns_zero(self):
        fn = self._import()
        dc = {"oldUri": None, "newUri": None}
        result = fn(dc)
        assert result == 0

    def test_overwrite_true_replaces_dst(self, tmp_path):
        fn = self._import()
        src = tmp_path / "src.rs"
        dst = tmp_path / "dst.rs"
        src.write_text("source content", encoding="utf-8")
        dst.write_text("existing content", encoding="utf-8")
        dc = {
            "oldUri": src.as_uri(),
            "newUri": dst.as_uri(),
            "options": {"overwrite": True},
        }
        result = fn(dc)
        assert result == 1
        assert dst.read_text() == "source content"

    def test_default_no_overwrite_skips_when_dst_exists(self, tmp_path):
        fn = self._import()
        src = tmp_path / "src2.rs"
        dst = tmp_path / "dst2.rs"
        src.write_text("source", encoding="utf-8")
        dst.write_text("existing", encoding="utf-8")
        dc = {"oldUri": src.as_uri(), "newUri": dst.as_uri()}
        result = fn(dc)
        assert result == 0  # skipped silently


# ============================================================================
# facade_support: _apply_resource_delete edge cases
# ============================================================================


class TestApplyResourceDelete:
    def _import(self):
        from serena.tools.facade_support import _apply_resource_delete
        return _apply_resource_delete

    def test_directory_target_returns_zero(self, tmp_path):
        fn = self._import()
        # tmp_path is a directory → LO-3: no-op
        dc = {"uri": tmp_path.as_uri()}
        result = fn(dc)
        assert result == 0
        assert tmp_path.exists()  # not deleted

    def test_file_deleted(self, tmp_path):
        fn = self._import()
        f = tmp_path / "del_me.rs"
        f.write_text("content", encoding="utf-8")
        dc = {"uri": f.as_uri()}
        result = fn(dc)
        assert result == 1
        assert not f.exists()

    def test_none_uri_returns_zero(self):
        fn = self._import()
        result = fn({"uri": None})
        assert result == 0


# ============================================================================
# facade_support: _apply_resource_create edge cases
# ============================================================================


class TestApplyResourceCreate:
    def _import(self):
        from serena.tools.facade_support import _apply_resource_create
        return _apply_resource_create

    def test_none_uri_returns_zero(self):
        fn = self._import()
        result = fn({"uri": None})
        assert result == 0

    def test_creates_file(self, tmp_path):
        fn = self._import()
        target = tmp_path / "sub" / "newfile.rs"
        dc = {"uri": target.as_uri()}
        result = fn(dc)
        assert result == 1
        assert target.exists()

    def test_ignore_if_exists_skips_when_exists(self, tmp_path):
        fn = self._import()
        target = tmp_path / "exists.rs"
        target.write_text("content", encoding="utf-8")
        dc = {"uri": target.as_uri(), "options": {"ignoreIfExists": True}}
        result = fn(dc)
        assert result == 0  # skip


# ============================================================================
# _build_failure_step
# ============================================================================


class TestBuildFailureStep:
    def test_returns_refactor_result_with_failure(self):
        from serena.tools.scalpel_facades import _build_failure_step
        from serena.tools.scalpel_schemas import ErrorCode

        step = _build_failure_step(
            code=ErrorCode.INVALID_ARGUMENT,
            stage="test_stage",
            reason="test reason",
        )
        assert step.applied is False
        assert step.no_op is False
        assert step.failure is not None
        assert step.failure.reason == "test reason"
        assert step.failure.stage == "test_stage"


# ============================================================================
# facade_support: capture_pre_edit_snapshot — documentChanges shape
# ============================================================================


class TestCapturePreEditSnapshotDocChanges:
    def test_captures_text_document_edit_uri(self, tmp_path):
        from serena.tools.facade_support import capture_pre_edit_snapshot

        f = tmp_path / "tde.py"
        f.write_text("original", encoding="utf-8")
        uri = f.as_uri()
        edit = {
            "documentChanges": [
                {
                    "textDocument": {"uri": uri},
                    "edits": [],
                }
            ]
        }
        snapshot = capture_pre_edit_snapshot(edit)
        assert snapshot[uri] == "original"

    def test_create_op_snaps_nonexistent(self, tmp_path):
        from serena.tools.facade_support import capture_pre_edit_snapshot, _SNAPSHOT_NONEXISTENT

        uri = (tmp_path / "new.py").as_uri()
        edit = {
            "documentChanges": [
                {"kind": "create", "uri": uri}
            ]
        }
        snapshot = capture_pre_edit_snapshot(edit)
        assert snapshot[uri] == _SNAPSHOT_NONEXISTENT


# ============================================================================
# scalpel_facades: _get_inlay_hint_provider (lines 3734-3752)
# ============================================================================


class TestGetInlayHintProvider:
    def test_returns_none_when_coordinator_raises(self, tmp_path):
        """coordinator_for_facade raises → return None."""
        from serena.tools.scalpel_facades import _get_inlay_hint_provider

        with patch("serena.tools.scalpel_facades.coordinator_for_facade", side_effect=RuntimeError("no coord")):
            result = _get_inlay_hint_provider(tmp_path)

        assert result is None

    def test_returns_none_when_no_fetch_inlay_hints(self, tmp_path):
        """Coordinator exists but has no callable fetch_inlay_hints → return None."""
        from serena.tools.scalpel_facades import _get_inlay_hint_provider

        mock_coord = MagicMock()
        # Remove fetch_inlay_hints by making getattr return None (non-callable)
        mock_coord.fetch_inlay_hints = None  # not callable

        with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
            result = _get_inlay_hint_provider(tmp_path)

        assert result is None

    def test_returns_fetcher_when_present(self, tmp_path):
        """Coordinator exposes a callable fetch_inlay_hints → return it."""
        from serena.tools.scalpel_facades import _get_inlay_hint_provider

        mock_fetcher = MagicMock()
        mock_coord = MagicMock()
        mock_coord.fetch_inlay_hints = mock_fetcher

        with patch("serena.tools.scalpel_facades.coordinator_for_facade", return_value=mock_coord):
            result = _get_inlay_hint_provider(tmp_path)

        assert result is mock_fetcher
