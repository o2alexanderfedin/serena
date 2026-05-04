"""PC1 Wave I: Closing remaining simple-branch gaps.

Targets:
- scalpel_facades._post_process_extract_edit lines 746 (non-str newText in documentChanges edits)
- scalpel_facades._substitute_introduced_parameter_name lines 801, 813, 816, 819
- scalpel_facades._run_async loop.is_running branch (line 271) via running loop
- facade_support._inverse_applier_to_disk OSError branches (lines 498-499, 527-528, 554-559, 568-569)
- facade_support._restore_text_uri_to_snapshot OSError branches (619-623, 629-633)
- facade_support._apply_resource_create overwrite (line 226 path)
- facade_support._resolve_winner_edit branches
- scalpel_primitives lines 220, 437-438, 530, 534, 561-562, 863, 880, 889
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# _post_process_extract_edit: non-str newText in documentChanges (line 746)
# ============================================================================


class TestPostProcessExtractEditNonStrInDocChanges:
    def test_non_str_newtext_in_doc_changes_edits_preserved(self):
        from serena.tools.scalpel_facades import _post_process_extract_edit

        edit = {
            "documentChanges": [
                {
                    "textDocument": {"uri": "file:///lib.rs"},
                    "edits": [
                        {"range": {}, "newText": 999},  # non-str → line 746
                    ],
                }
            ]
        }
        result = _post_process_extract_edit(edit, new_name="my_func", visibility_prefix="")
        assert result["documentChanges"][0]["edits"][0]["newText"] == 999

    def test_non_str_newtext_in_changes_preserved(self):
        from serena.tools.scalpel_facades import _post_process_extract_edit

        edit = {
            "changes": {
                "file:///lib.rs": [
                    {"range": {}, "newText": None},  # non-str → line 801
                ]
            }
        }
        result = _post_process_extract_edit(edit, new_name="new_function", visibility_prefix="")
        assert result["changes"]["file:///lib.rs"][0]["newText"] is None


# ============================================================================
# _substitute_introduced_parameter_name: non-str/non-dict branches
# ============================================================================


class TestSubstituteIntroducedParameterNameBranches:
    def test_non_str_newtext_in_changes_preserved(self):
        """Line 801: non-str newText in changes → appended as-is."""
        from serena.tools.scalpel_facades import _substitute_introduced_parameter_name

        edit = {
            "changes": {
                "file:///x.py": [
                    {"range": {}, "newText": 42},  # non-str
                ]
            }
        }
        result = _substitute_introduced_parameter_name(edit, parameter_name="value")
        assert result["changes"]["file:///x.py"][0]["newText"] == 42

    def test_non_dict_edit_in_changes_preserved(self):
        """Non-dict edit in changes → appended as-is (line 801 branch)."""
        from serena.tools.scalpel_facades import _substitute_introduced_parameter_name

        edit = {
            "changes": {
                "file:///x.py": [
                    "not_a_dict",  # non-dict
                ]
            }
        }
        result = _substitute_introduced_parameter_name(edit, parameter_name="value")
        assert result["changes"]["file:///x.py"][0] == "not_a_dict"

    def test_non_str_newtext_in_document_changes_edits_preserved(self):
        """Line 813: non-str newText in documentChanges edits → appended as-is."""
        from serena.tools.scalpel_facades import _substitute_introduced_parameter_name

        edit = {
            "documentChanges": [
                {
                    "textDocument": {"uri": "file:///x.py"},
                    "edits": [{"range": {}, "newText": 99}],  # non-str
                }
            ]
        }
        result = _substitute_introduced_parameter_name(edit, parameter_name="value")
        assert result["documentChanges"][0]["edits"][0]["newText"] == 99

    def test_non_dict_entry_in_document_changes_preserved(self):
        """Line 816: non-dict entry in documentChanges (no 'edits') → appended as-is."""
        from serena.tools.scalpel_facades import _substitute_introduced_parameter_name

        edit = {
            "documentChanges": [
                {"kind": "create", "uri": "file:///new.py"},  # no 'edits'
            ]
        }
        result = _substitute_introduced_parameter_name(edit, parameter_name="value")
        assert result["documentChanges"][0]["kind"] == "create"

    def test_other_keys_passed_through(self):
        """Line 819: non-changes/non-documentChanges keys → passed through unchanged."""
        from serena.tools.scalpel_facades import _substitute_introduced_parameter_name

        edit = {"version": 1, "otherKey": "x"}
        result = _substitute_introduced_parameter_name(edit, parameter_name="value")
        assert result["version"] == 1
        assert result["otherKey"] == "x"



# ============================================================================
# facade_support._resolve_winner_edit branches
# ============================================================================


class TestResolveWinnerEdit:
    def test_no_id_returns_none(self):
        """Winner has no id/action_id → return None."""
        from serena.tools.facade_support import _resolve_winner_edit

        coord = MagicMock()
        winner = MagicMock()
        winner.id = None
        winner.action_id = None

        result = _resolve_winner_edit(coord, winner)
        assert result is None

    def test_no_get_action_edit_returns_none(self):
        """Coord has no get_action_edit callable → return None."""
        from serena.tools.facade_support import _resolve_winner_edit

        coord = MagicMock()
        del coord.get_action_edit  # make it not callable/exist via spec
        coord.get_action_edit = None  # non-callable

        winner = MagicMock()
        winner.id = "action-123"
        winner.action_id = None

        result = _resolve_winner_edit(coord, winner)
        assert result is None

    def test_get_action_edit_returns_non_dict_returns_none(self):
        """get_action_edit returns non-dict → return None."""
        from serena.tools.facade_support import _resolve_winner_edit

        coord = MagicMock()
        coord.get_action_edit.return_value = "not-a-dict"

        winner = MagicMock()
        winner.id = "action-123"
        winner.action_id = None

        result = _resolve_winner_edit(coord, winner)
        assert result is None

    def test_get_action_edit_returns_dict_returned(self):
        """get_action_edit returns dict → return it."""
        from serena.tools.facade_support import _resolve_winner_edit

        edit = {"changes": {}}
        coord = MagicMock()
        coord.get_action_edit.return_value = edit

        winner = MagicMock()
        winner.id = "action-123"
        winner.action_id = None

        result = _resolve_winner_edit(coord, winner)
        assert result is edit


# ============================================================================
# facade_support._inverse_applier_to_disk OSError / edge-case branches
# ============================================================================


class TestInverseApplierOSErrorBranches:
    def test_inverse_create_oserror_adds_warning(self, tmp_path):
        """Lines 498-499: OSError when deleting created file → warning added."""
        from serena.tools.facade_support import _inverse_applier_to_disk

        f = tmp_path / "created.py"
        f.write_text("content", encoding="utf-8")
        uri = f.as_uri()

        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            restored, warnings = _inverse_applier_to_disk(
                {},  # snapshot
                {"documentChanges": [{"kind": "create", "uri": uri}]},  # applied_edit
            )

        assert any("inverse(create)" in w for w in warnings)

    def test_inverse_delete_with_snapshot_oserror_adds_warning(self, tmp_path):
        """Lines 527-528: OSError when recreating deleted file → warning."""
        from serena.tools.facade_support import _inverse_applier_to_disk

        f = tmp_path / "deleted.py"
        uri = f.as_uri()
        snapshot = {uri: "original content"}

        with patch.object(Path, "write_text", side_effect=OSError("no write")):
            restored, warnings = _inverse_applier_to_disk(
                snapshot,  # snapshot
                {"documentChanges": [{"kind": "delete", "uri": uri}]},  # applied_edit
            )

        assert any("inverse(delete)" in w for w in warnings)

    def test_inverse_rename_old_uri_not_string_continues(self, tmp_path):
        """Line 535: oldUri not a string → continue."""
        from serena.tools.facade_support import _inverse_applier_to_disk

        restored, warnings = _inverse_applier_to_disk(
            {},  # snapshot
            {"documentChanges": [{"kind": "rename", "oldUri": None, "newUri": "file:///x.py"}]},
        )
        # No warning; just silently skipped
        assert restored is False

    def test_inverse_delete_non_string_uri_continues(self):
        """Line 508-509: delete URI not a string → continue."""
        from serena.tools.facade_support import _inverse_applier_to_disk

        restored, warnings = _inverse_applier_to_disk(
            {},  # snapshot
            {"documentChanges": [{"kind": "delete", "uri": None}]},
        )
        assert restored is False


# ============================================================================
# facade_support._restore_text_uri_to_snapshot OSError branches
# ============================================================================


class TestRestoreTextUriToSnapshotOSError:
    def test_unlink_oserror_returns_false(self, tmp_path):
        """Lines 619-623: OSError when deleting created file → return False."""
        from serena.tools.facade_support import _restore_text_uri_to_snapshot, _SNAPSHOT_NONEXISTENT

        f = tmp_path / "new.py"
        f.write_text("content", encoding="utf-8")
        uri = f.as_uri()
        warnings = []

        with patch.object(Path, "unlink", side_effect=OSError("cannot delete")):
            result = _restore_text_uri_to_snapshot(
                uri, snapshot={uri: _SNAPSHOT_NONEXISTENT}, warnings=warnings
            )

        assert result is False
        assert any("cannot delete" in w for w in warnings)

    def test_write_oserror_returns_false(self, tmp_path):
        """Lines 629-633: OSError when writing content → return False."""
        from serena.tools.facade_support import _restore_text_uri_to_snapshot

        f = tmp_path / "restore.py"
        uri = f.as_uri()
        warnings = []

        with patch.object(Path, "write_text", side_effect=OSError("cannot write")):
            result = _restore_text_uri_to_snapshot(
                uri, snapshot={uri: "original content"}, warnings=warnings
            )

        assert result is False
        assert any("cannot write" in w for w in warnings)


# ============================================================================
# scalpel_primitives: lines 220, 437-438, 530, 534, 561-562, 863, 880, 889
# ============================================================================


class TestScalpelPrimitivesSmallBranches:
    def test_run_async_runtime_error_uses_new_loop(self):
        """Line 221-222: RuntimeError from get_event_loop → use new_event_loop."""
        from serena.tools.scalpel_primitives import _run_async

        async def coro():
            return 77

        # Patch get_event_loop to raise RuntimeError → falls to new_event_loop path
        with patch("asyncio.get_event_loop", side_effect=RuntimeError("no loop")):
            result = _run_async(coro())

        assert result == 77
