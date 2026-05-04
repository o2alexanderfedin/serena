"""PC1 — unit tests for facade_support.py helper functions.

Targets the 195 uncovered lines in facade_support.py by exercising:
- _uri_to_path, _lsp_position_to_offset, _splice_text_edit
- _apply_text_edits_to_file_uri, _apply_workspace_edit_to_disk
- Resource ops: _apply_resource_create, _apply_resource_rename, _apply_resource_delete
- _resource_uri_to_path
- capture_pre_edit_snapshot, _read_pre_edit_or_sentinel
- _inverse_applier_to_disk and _restore_text_uri_to_snapshot
- build_failure_result, workspace_boundary_guard
- resolve_capability_for_facade, FACADE_TO_CAPABILITY_ID
- apply_workspace_edit_and_checkpoint
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.facade_support import (
    FACADE_TO_CAPABILITY_ID,
    _SNAPSHOT_NONEXISTENT,
    _apply_resource_create,
    _apply_resource_delete,
    _apply_resource_rename,
    _apply_text_edits_to_file_uri,
    _apply_workspace_edit_to_disk,
    _inverse_applier_to_disk,
    _lsp_position_to_offset,
    _read_pre_edit_or_sentinel,
    _resource_uri_to_path,
    _resolve_winner_edit,
    _restore_text_uri_to_snapshot,
    _splice_text_edit,
    _uri_to_path,
    apply_workspace_edit_and_checkpoint,
    build_failure_result,
    capture_pre_edit_snapshot,
    resolve_capability_for_facade,
    workspace_boundary_guard,
)
from serena.tools.scalpel_schemas import ErrorCode


# ---------------------------------------------------------------------------
# _uri_to_path
# ---------------------------------------------------------------------------


def test_uri_to_path_non_file_uri_returns_none() -> None:
    result = _uri_to_path("http://example.com/foo.py")
    assert result is None


def test_uri_to_path_file_uri_returns_path() -> None:
    result = _uri_to_path("file:///tmp/foo.py")
    assert result is not None
    assert str(result) == "/tmp/foo.py"


def test_uri_to_path_encoded_spaces() -> None:
    result = _uri_to_path("file:///tmp/my%20file.py")
    assert result is not None
    assert result.name == "my file.py"


# ---------------------------------------------------------------------------
# _resource_uri_to_path
# ---------------------------------------------------------------------------


def test_resource_uri_to_path_non_file_returns_none() -> None:
    assert _resource_uri_to_path("ftp://server/path") is None


def test_resource_uri_to_path_none_input_returns_none() -> None:
    assert _resource_uri_to_path(None) is None  # type: ignore[arg-type]


def test_resource_uri_to_path_non_string_returns_none() -> None:
    assert _resource_uri_to_path(42) is None  # type: ignore[arg-type]


def test_resource_uri_to_path_valid_file_uri() -> None:
    result = _resource_uri_to_path("file:///tmp/bar.py")
    assert result == Path("/tmp/bar.py")


# ---------------------------------------------------------------------------
# _lsp_position_to_offset
# ---------------------------------------------------------------------------


def test_lsp_position_to_offset_line_0_character_0() -> None:
    lines = ["hello\n", "world\n"]
    assert _lsp_position_to_offset(lines, 0, 0) == 0


def test_lsp_position_to_offset_second_line() -> None:
    lines = ["hello\n", "world\n"]
    # offset at start of line 1 = 6 (len("hello\n"))
    assert _lsp_position_to_offset(lines, 1, 0) == 6


def test_lsp_position_to_offset_negative_line() -> None:
    lines = ["hello\n", "world\n"]
    assert _lsp_position_to_offset(lines, -1, 0) == 0


def test_lsp_position_to_offset_line_beyond_end() -> None:
    lines = ["hello\n", "world\n"]
    result = _lsp_position_to_offset(lines, 99, 0)
    assert result == sum(len(l) for l in lines)


def test_lsp_position_to_offset_character_clamped_to_visible_length() -> None:
    lines = ["hello\n"]
    # "hello" has 5 visible chars; character=100 clamps to 5
    assert _lsp_position_to_offset(lines, 0, 100) == 5


# ---------------------------------------------------------------------------
# _splice_text_edit
# ---------------------------------------------------------------------------


def test_splice_text_edit_basic_replacement() -> None:
    source = "hello world\n"
    edit: dict[str, Any] = {
        "range": {
            "start": {"line": 0, "character": 6},
            "end": {"line": 0, "character": 11},
        },
        "newText": "earth",
    }
    result = _splice_text_edit(source, edit)
    assert result == "hello earth\n"


def test_splice_text_edit_zero_width_insertion() -> None:
    source = "ab\n"
    edit: dict[str, Any] = {
        "range": {
            "start": {"line": 0, "character": 1},
            "end": {"line": 0, "character": 1},
        },
        "newText": "X",
    }
    result = _splice_text_edit(source, edit)
    assert result == "aXb\n"


def test_splice_text_edit_idempotence_guard() -> None:
    """If the newText is already at start_offset, skip re-splicing."""
    source = "aXb\n"
    # This edit was already applied — trying to insert "X" at (0,1)→(0,1)
    # but the text at position 1 is already "X", and end <= start + len("X").
    edit: dict[str, Any] = {
        "range": {
            "start": {"line": 0, "character": 1},
            "end": {"line": 0, "character": 1},
        },
        "newText": "X",
    }
    result = _splice_text_edit(source, edit)
    # Idempotence: X is already there, guard triggers
    assert result == "aXb\n"


# ---------------------------------------------------------------------------
# _apply_text_edits_to_file_uri — file system tests
# ---------------------------------------------------------------------------


def test_apply_text_edits_non_file_uri_returns_zero() -> None:
    count = _apply_text_edits_to_file_uri("http://example.com/foo.py", [])
    assert count == 0


def test_apply_text_edits_empty_edits_returns_zero() -> None:
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(b"hello\n")
        path = f.name
    try:
        uri = Path(path).as_uri()
        count = _apply_text_edits_to_file_uri(uri, [])
        assert count == 0
    finally:
        os.unlink(path)


def test_apply_text_edits_missing_file_returns_zero() -> None:
    uri = "file:///nonexistent_path_xyzzy_12345/foo.py"
    edits = [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}}, "newText": "x"}]
    count = _apply_text_edits_to_file_uri(uri, edits)
    assert count == 0


def test_apply_text_edits_applies_edit_to_disk() -> None:
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
        f.write("hello world\n")
        path = f.name
    try:
        uri = Path(path).as_uri()
        edits = [{
            "range": {
                "start": {"line": 0, "character": 6},
                "end": {"line": 0, "character": 11},
            },
            "newText": "earth",
        }]
        count = _apply_text_edits_to_file_uri(uri, edits)
        assert count == 1
        assert Path(path).read_text() == "hello earth\n"
    finally:
        os.unlink(path)


def test_apply_text_edits_idempotent_no_op() -> None:
    """Re-applying the same edit should be a no-op (returns 0)."""
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
        f.write("hello earth\n")
        path = f.name
    try:
        uri = Path(path).as_uri()
        edits = [{
            "range": {
                "start": {"line": 0, "character": 6},
                "end": {"line": 0, "character": 11},
            },
            "newText": "earth",
        }]
        count = _apply_text_edits_to_file_uri(uri, edits)
        assert count == 0
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# _apply_workspace_edit_to_disk — changes shape
# ---------------------------------------------------------------------------


def test_apply_workspace_edit_changes_shape() -> None:
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
        f.write("foo\n")
        path = f.name
    try:
        uri = Path(path).as_uri()
        edit = {"changes": {uri: [{
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
            "newText": "bar",
        }]}}
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 1
        assert Path(path).read_text() == "bar\n"
    finally:
        os.unlink(path)


def test_apply_workspace_edit_document_changes_text_doc_edit() -> None:
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
        f.write("abc\n")
        path = f.name
    try:
        uri = Path(path).as_uri()
        edit = {"documentChanges": [{
            "textDocument": {"uri": uri, "version": None},
            "edits": [{
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
                "newText": "xyz",
            }],
        }]}
        count = _apply_workspace_edit_to_disk(edit)
        assert count == 1
        assert Path(path).read_text() == "xyz\n"
    finally:
        os.unlink(path)


def test_apply_workspace_edit_unknown_kind_skipped() -> None:
    """Unknown kind in documentChanges must not crash; count stays 0."""
    edit = {"documentChanges": [{"kind": "unknownFutureOp", "uri": "file:///x.py"}]}
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 0


def test_apply_workspace_edit_non_dict_document_changes_skipped() -> None:
    edit = {"documentChanges": ["not a dict"]}
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 0


# ---------------------------------------------------------------------------
# Resource ops: _apply_resource_create
# ---------------------------------------------------------------------------


def test_apply_resource_create_creates_new_file(tmp_path: Path) -> None:
    target = tmp_path / "newfile.py"
    uri = target.as_uri()
    count = _apply_resource_create({"uri": uri})
    assert count == 1
    assert target.exists()
    assert target.read_text() == ""


def test_apply_resource_create_ignore_if_exists_default(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.write_text("original")
    uri = target.as_uri()
    count = _apply_resource_create({"uri": uri})
    assert count == 0
    assert target.read_text() == "original"


def test_apply_resource_create_overwrite_when_flag_set(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.write_text("original")
    uri = target.as_uri()
    count = _apply_resource_create({"uri": uri, "options": {"overwrite": True}})
    assert count == 1
    assert target.read_text() == ""


def test_apply_resource_create_invalid_uri_returns_zero() -> None:
    count = _apply_resource_create({"uri": "ftp://server/file.py"})
    assert count == 0


def test_apply_resource_create_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "file.py"
    count = _apply_resource_create({"uri": target.as_uri()})
    assert count == 1
    assert target.exists()


# ---------------------------------------------------------------------------
# Resource ops: _apply_resource_rename
# ---------------------------------------------------------------------------


def test_apply_resource_rename_basic(tmp_path: Path) -> None:
    src = tmp_path / "old.py"
    src.write_text("content")
    dst = tmp_path / "new.py"
    count = _apply_resource_rename({"oldUri": src.as_uri(), "newUri": dst.as_uri()})
    assert count == 1
    assert dst.exists()
    assert not src.exists()


def test_apply_resource_rename_src_missing_returns_zero(tmp_path: Path) -> None:
    count = _apply_resource_rename({
        "oldUri": (tmp_path / "ghost.py").as_uri(),
        "newUri": (tmp_path / "dst.py").as_uri(),
    })
    assert count == 0


def test_apply_resource_rename_dst_exists_no_overwrite_returns_zero(tmp_path: Path) -> None:
    src = tmp_path / "src.py"
    src.write_text("src")
    dst = tmp_path / "dst.py"
    dst.write_text("dst")
    count = _apply_resource_rename({"oldUri": src.as_uri(), "newUri": dst.as_uri()})
    assert count == 0
    assert src.exists()  # src not renamed


def test_apply_resource_rename_dst_exists_with_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "src.py"
    src.write_text("src")
    dst = tmp_path / "dst.py"
    dst.write_text("dst")
    count = _apply_resource_rename({
        "oldUri": src.as_uri(),
        "newUri": dst.as_uri(),
        "options": {"overwrite": True},
    })
    assert count == 1
    assert dst.read_text() == "src"


def test_apply_resource_rename_dst_exists_ignore_if_exists(tmp_path: Path) -> None:
    src = tmp_path / "src.py"
    src.write_text("src")
    dst = tmp_path / "dst.py"
    dst.write_text("dst")
    count = _apply_resource_rename({
        "oldUri": src.as_uri(),
        "newUri": dst.as_uri(),
        "options": {"ignoreIfExists": True},
    })
    assert count == 0


def test_apply_resource_rename_invalid_uri_returns_zero() -> None:
    count = _apply_resource_rename({"oldUri": None, "newUri": "file:///x.py"})
    assert count == 0


# ---------------------------------------------------------------------------
# Resource ops: _apply_resource_delete
# ---------------------------------------------------------------------------


def test_apply_resource_delete_basic(tmp_path: Path) -> None:
    target = tmp_path / "del.py"
    target.write_text("data")
    count = _apply_resource_delete({"uri": target.as_uri()})
    assert count == 1
    assert not target.exists()


def test_apply_resource_delete_missing_file_ignore_if_not_exists(tmp_path: Path) -> None:
    count = _apply_resource_delete({"uri": (tmp_path / "ghost.py").as_uri()})
    assert count == 0


def test_apply_resource_delete_directory_is_noop(tmp_path: Path) -> None:
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    count = _apply_resource_delete({"uri": subdir.as_uri()})
    assert count == 0
    assert subdir.exists()


def test_apply_resource_delete_invalid_uri_returns_zero() -> None:
    count = _apply_resource_delete({"uri": "ftp://server/x.py"})
    assert count == 0


# ---------------------------------------------------------------------------
# _apply_workspace_edit_to_disk — resource op integration
# ---------------------------------------------------------------------------


def test_apply_workspace_edit_create_op(tmp_path: Path) -> None:
    target = tmp_path / "created.py"
    edit = {"documentChanges": [{"kind": "create", "uri": target.as_uri()}]}
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 1
    assert target.exists()


def test_apply_workspace_edit_rename_op(tmp_path: Path) -> None:
    src = tmp_path / "old.py"
    src.write_text("data")
    dst = tmp_path / "new.py"
    edit = {"documentChanges": [{"kind": "rename", "oldUri": src.as_uri(), "newUri": dst.as_uri()}]}
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 1
    assert dst.exists()


def test_apply_workspace_edit_delete_op(tmp_path: Path) -> None:
    target = tmp_path / "to_delete.py"
    target.write_text("bye")
    edit = {"documentChanges": [{"kind": "delete", "uri": target.as_uri()}]}
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 1
    assert not target.exists()


def test_apply_workspace_edit_missing_uri_in_text_doc_edit_skips() -> None:
    edit = {"documentChanges": [{
        "textDocument": {"uri": 12345},  # not a string
        "edits": [],
    }]}
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 0


# ---------------------------------------------------------------------------
# capture_pre_edit_snapshot
# ---------------------------------------------------------------------------


def test_capture_pre_edit_snapshot_changes_shape(tmp_path: Path) -> None:
    f = tmp_path / "foo.py"
    f.write_text("original content")
    uri = f.as_uri()
    edit = {"changes": {uri: [{"range": {}, "newText": "x"}]}}
    snapshot = capture_pre_edit_snapshot(edit)
    assert uri in snapshot
    assert snapshot[uri] == "original content"


def test_capture_pre_edit_snapshot_missing_file(tmp_path: Path) -> None:
    uri = (tmp_path / "nonexistent.py").as_uri()
    edit = {"changes": {uri: []}}
    snapshot = capture_pre_edit_snapshot(edit)
    assert snapshot[uri] == _SNAPSHOT_NONEXISTENT


def test_capture_pre_edit_snapshot_create_kind_records_sentinel(tmp_path: Path) -> None:
    target = tmp_path / "newfile.py"
    edit = {"documentChanges": [{"kind": "create", "uri": target.as_uri()}]}
    snapshot = capture_pre_edit_snapshot(edit)
    assert snapshot[target.as_uri()] == _SNAPSHOT_NONEXISTENT


def test_capture_pre_edit_snapshot_delete_kind_records_sentinel(tmp_path: Path) -> None:
    target = tmp_path / "file.py"
    target.write_text("content")
    edit = {"documentChanges": [{"kind": "delete", "uri": target.as_uri()}]}
    snapshot = capture_pre_edit_snapshot(edit)
    assert snapshot[target.as_uri()] == _SNAPSHOT_NONEXISTENT


def test_capture_pre_edit_snapshot_rename_kind_records_old_uri(tmp_path: Path) -> None:
    old_file = tmp_path / "old.py"
    old_file.write_text("old content")
    edit = {"documentChanges": [{
        "kind": "rename",
        "oldUri": old_file.as_uri(),
        "newUri": (tmp_path / "new.py").as_uri(),
    }]}
    snapshot = capture_pre_edit_snapshot(edit)
    assert snapshot[old_file.as_uri()] == "old content"


def test_capture_pre_edit_snapshot_text_doc_edit_in_document_changes(tmp_path: Path) -> None:
    f = tmp_path / "doc.py"
    f.write_text("hello")
    edit = {"documentChanges": [{
        "textDocument": {"uri": f.as_uri()},
        "edits": [],
    }]}
    snapshot = capture_pre_edit_snapshot(edit)
    assert snapshot[f.as_uri()] == "hello"


def test_capture_pre_edit_snapshot_empty_edit_returns_empty() -> None:
    snapshot = capture_pre_edit_snapshot({})
    assert snapshot == {}


# ---------------------------------------------------------------------------
# _read_pre_edit_or_sentinel
# ---------------------------------------------------------------------------


def test_read_pre_edit_or_sentinel_non_file_uri() -> None:
    result = _read_pre_edit_or_sentinel("http://example.com/foo.py")
    assert result == _SNAPSHOT_NONEXISTENT


def test_read_pre_edit_or_sentinel_missing_file(tmp_path: Path) -> None:
    uri = (tmp_path / "ghost.py").as_uri()
    result = _read_pre_edit_or_sentinel(uri)
    assert result == _SNAPSHOT_NONEXISTENT


def test_read_pre_edit_or_sentinel_existing_file(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("hello")
    result = _read_pre_edit_or_sentinel(f.as_uri())
    assert result == "hello"


# ---------------------------------------------------------------------------
# _restore_text_uri_to_snapshot
# ---------------------------------------------------------------------------


def test_restore_text_uri_non_file_uri_returns_false() -> None:
    warnings: list[str] = []
    ok = _restore_text_uri_to_snapshot("http://example.com/foo.py", {}, warnings)
    assert not ok
    assert any("non-file URI" in w for w in warnings)


def test_restore_text_uri_no_snapshot_entry_returns_false(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("current")
    warnings: list[str] = []
    ok = _restore_text_uri_to_snapshot(f.as_uri(), {}, warnings)
    assert not ok
    assert any("no snapshot entry" in w for w in warnings)


def test_restore_text_uri_sentinel_deletes_file(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("created by apply")
    warnings: list[str] = []
    snapshot = {f.as_uri(): _SNAPSHOT_NONEXISTENT}
    ok = _restore_text_uri_to_snapshot(f.as_uri(), snapshot, warnings)
    assert ok
    assert not f.exists()


def test_restore_text_uri_sentinel_when_file_missing_returns_false(tmp_path: Path) -> None:
    f = tmp_path / "ghost.py"
    warnings: list[str] = []
    snapshot = {f.as_uri(): _SNAPSHOT_NONEXISTENT}
    ok = _restore_text_uri_to_snapshot(f.as_uri(), snapshot, warnings)
    assert not ok


def test_restore_text_uri_standard_restore(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("new content")
    warnings: list[str] = []
    snapshot = {f.as_uri(): "old content"}
    ok = _restore_text_uri_to_snapshot(f.as_uri(), snapshot, warnings)
    assert ok
    assert f.read_text() == "old content"
    assert warnings == []


# ---------------------------------------------------------------------------
# _inverse_applier_to_disk — text edits path
# ---------------------------------------------------------------------------


def test_inverse_applier_text_edit_restores_content(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("new content")
    uri = f.as_uri()
    snapshot = {uri: "old content"}
    applied_edit = {"changes": {uri: []}}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    assert ok
    assert f.read_text() == "old content"
    assert warnings == []


def test_inverse_applier_create_op_rolled_back(tmp_path: Path) -> None:
    f = tmp_path / "created.py"
    f.write_text("")
    uri = f.as_uri()
    snapshot = {uri: _SNAPSHOT_NONEXISTENT}
    applied_edit = {"documentChanges": [{"kind": "create", "uri": uri}]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    assert ok
    assert not f.exists()


def test_inverse_applier_delete_op_irreversible_emits_warning(tmp_path: Path) -> None:
    f = tmp_path / "deleted.py"
    uri = f.as_uri()
    snapshot = {uri: _SNAPSHOT_NONEXISTENT}
    applied_edit = {"documentChanges": [{"kind": "delete", "uri": uri}]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    assert not ok
    assert any("inverse(delete)" in w and "cannot be undone" in w for w in warnings)


def test_inverse_applier_delete_op_with_captured_content(tmp_path: Path) -> None:
    """If a delete op has captured content in snapshot, recreate the file."""
    f = tmp_path / "recovered.py"
    uri = f.as_uri()
    snapshot = {uri: "original content"}
    applied_edit = {"documentChanges": [{"kind": "delete", "uri": uri}]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    assert ok
    assert f.exists()
    assert f.read_text() == "original content"


def test_inverse_applier_rename_op_rolled_back(tmp_path: Path) -> None:
    new_file = tmp_path / "new.py"
    new_file.write_text("content after rename")
    old_uri = (tmp_path / "old.py").as_uri()
    new_uri = new_file.as_uri()
    snapshot = {old_uri: "original content"}
    applied_edit = {"documentChanges": [{"kind": "rename", "oldUri": old_uri, "newUri": new_uri}]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    assert ok
    old_path = tmp_path / "old.py"
    assert old_path.exists()
    assert old_path.read_text() == "original content"


def test_inverse_applier_rename_when_new_file_missing_recovers(tmp_path: Path) -> None:
    old_uri = (tmp_path / "old.py").as_uri()
    new_uri = (tmp_path / "new.py").as_uri()
    snapshot = {old_uri: "content"}
    applied_edit = {"documentChanges": [{"kind": "rename", "oldUri": old_uri, "newUri": new_uri}]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    # new file is missing — warning emitted, but old dir created
    assert any("no longer exists" in w for w in warnings)


def test_inverse_applier_rename_no_snapshot_content_restores_only(tmp_path: Path) -> None:
    new_file = tmp_path / "new.py"
    new_file.write_text("content")
    old_uri = (tmp_path / "old.py").as_uri()
    new_uri = new_file.as_uri()
    # No snapshot for old_uri
    snapshot: dict[str, str] = {}
    applied_edit = {"documentChanges": [{"kind": "rename", "oldUri": old_uri, "newUri": new_uri}]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    assert ok


def test_inverse_applier_non_dict_in_document_changes_skipped(tmp_path: Path) -> None:
    snapshot: dict[str, str] = {}
    applied_edit = {"documentChanges": ["not_a_dict"]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    assert not ok
    assert warnings == []


def test_inverse_applier_text_doc_edit_in_document_changes(tmp_path: Path) -> None:
    f = tmp_path / "f.py"
    f.write_text("new content")
    uri = f.as_uri()
    snapshot = {uri: "old content"}
    applied_edit = {"documentChanges": [{
        "textDocument": {"uri": uri},
        "edits": [],
    }]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    assert ok
    assert f.read_text() == "old content"


def test_inverse_applier_create_op_file_already_gone(tmp_path: Path) -> None:
    uri = (tmp_path / "already_gone.py").as_uri()
    snapshot = {uri: _SNAPSHOT_NONEXISTENT}
    applied_edit = {"documentChanges": [{"kind": "create", "uri": uri}]}
    ok, warnings = _inverse_applier_to_disk(snapshot, applied_edit)
    # File already gone — not ok, no warnings
    assert not ok


def test_inverse_applier_create_op_non_file_uri_emits_warning() -> None:
    applied_edit = {"documentChanges": [{"kind": "create", "uri": "http://example.com/f.py"}]}
    ok, warnings = _inverse_applier_to_disk({}, applied_edit)
    assert not ok
    assert any("non-file URI" in w for w in warnings)


def test_inverse_applier_delete_op_non_string_uri_skipped() -> None:
    applied_edit = {"documentChanges": [{"kind": "delete", "uri": 12345}]}
    ok, warnings = _inverse_applier_to_disk({}, applied_edit)
    assert not ok


# ---------------------------------------------------------------------------
# build_failure_result
# ---------------------------------------------------------------------------


def test_build_failure_result_default_recoverable() -> None:
    result = build_failure_result(
        code=ErrorCode.SYMBOL_NOT_FOUND,
        stage="test_stage",
        reason="Symbol not found",
    )
    assert result.applied is False
    assert result.failure is not None
    assert result.failure.code == ErrorCode.SYMBOL_NOT_FOUND
    assert result.failure.stage == "test_stage"
    assert result.failure.reason == "Symbol not found"
    assert result.failure.recoverable is True


def test_build_failure_result_non_recoverable() -> None:
    result = build_failure_result(
        code=ErrorCode.WORKSPACE_BOUNDARY_VIOLATION,
        stage="boundary_guard",
        reason="Outside workspace",
        recoverable=False,
    )
    assert result.failure is not None
    assert result.failure.recoverable is False


def test_build_failure_result_with_candidates() -> None:
    result = build_failure_result(
        code=ErrorCode.SYMBOL_NOT_FOUND,
        stage="s",
        reason="r",
        candidates=("foo", "bar"),
    )
    assert result.failure is not None
    assert "foo" in result.failure.candidates
    assert "bar" in result.failure.candidates


def test_build_failure_result_serializes_as_json() -> None:
    result = build_failure_result(
        code=ErrorCode.INVALID_ARGUMENT,
        stage="s",
        reason="bad arg",
    )
    payload = json.loads(result.model_dump_json(indent=2))
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


# ---------------------------------------------------------------------------
# workspace_boundary_guard
# ---------------------------------------------------------------------------


def test_workspace_boundary_guard_allow_out_of_workspace() -> None:
    result = workspace_boundary_guard(
        file="/outside/project.py",
        project_root=Path("/my/project"),
        allow_out_of_workspace=True,
    )
    assert result is None


def test_workspace_boundary_guard_inside_workspace(tmp_path: Path) -> None:
    f = tmp_path / "src" / "main.py"
    f.parent.mkdir()
    f.write_text("pass")
    result = workspace_boundary_guard(
        file=str(f),
        project_root=tmp_path,
        allow_out_of_workspace=False,
    )
    assert result is None


def test_workspace_boundary_guard_outside_workspace(tmp_path: Path) -> None:
    # Create two separate temp dirs so one is clearly outside the other.
    other = Path(tempfile.mkdtemp())
    try:
        result = workspace_boundary_guard(
            file=str(other / "intruder.py"),
            project_root=tmp_path,
            allow_out_of_workspace=False,
        )
        assert result is not None
        assert result.failure is not None
        assert result.failure.code == ErrorCode.WORKSPACE_BOUNDARY_VIOLATION
        assert result.failure.recoverable is False
    finally:
        other.rmdir()


# ---------------------------------------------------------------------------
# FACADE_TO_CAPABILITY_ID — static map shape assertions
# ---------------------------------------------------------------------------


def test_facade_to_capability_id_has_expected_facades() -> None:
    for facade in ("split_file", "extract", "inline", "rename", "imports_organize"):
        assert facade in FACADE_TO_CAPABILITY_ID, f"Missing {facade!r}"


def test_facade_to_capability_id_rust_and_python_entries() -> None:
    for facade, langs in FACADE_TO_CAPABILITY_ID.items():
        assert "rust" in langs or "python" in langs, f"{facade!r} has neither rust nor python"


# ---------------------------------------------------------------------------
# resolve_capability_for_facade
# ---------------------------------------------------------------------------


def test_resolve_capability_for_facade_known_facade_rust() -> None:
    # Must import ScalpelRuntime lazily so singleton can be reset.
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.capabilities import CapabilityRecord, CapabilityCatalog
    mock_record = MagicMock(spec=CapabilityRecord)
    mock_record.id = "rust.refactor.extract.function"
    mock_catalog = MagicMock(spec=CapabilityCatalog)
    mock_catalog.records = [mock_record]
    mock_runtime = MagicMock()
    mock_runtime.catalog.return_value = mock_catalog

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = resolve_capability_for_facade("extract", language="rust")
    assert result is mock_record


def test_resolve_capability_for_facade_unknown_facade_returns_none() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.capabilities import CapabilityCatalog
    mock_catalog = MagicMock(spec=CapabilityCatalog)
    mock_catalog.records = []
    mock_runtime = MagicMock()
    mock_runtime.catalog.return_value = mock_catalog

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = resolve_capability_for_facade("nonexistent_facade", language="rust")
    assert result is None


def test_resolve_capability_for_facade_legacy_prefix_normalised() -> None:
    """Legacy ``scalpel_extract`` resolves the same as ``extract``."""
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.capabilities import CapabilityRecord, CapabilityCatalog
    mock_record = MagicMock(spec=CapabilityRecord)
    mock_record.id = "rust.refactor.extract.function"
    mock_catalog = MagicMock(spec=CapabilityCatalog)
    mock_catalog.records = [mock_record]
    mock_runtime = MagicMock()
    mock_runtime.catalog.return_value = mock_catalog

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = resolve_capability_for_facade("scalpel_extract", language="rust")
    assert result is mock_record


def test_resolve_capability_for_facade_override_used_when_provided() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.capabilities import CapabilityRecord, CapabilityCatalog
    mock_record = MagicMock(spec=CapabilityRecord)
    mock_record.id = "custom.capability.id"
    mock_catalog = MagicMock(spec=CapabilityCatalog)
    mock_catalog.records = [mock_record]
    mock_runtime = MagicMock()
    mock_runtime.catalog.return_value = mock_catalog

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = resolve_capability_for_facade(
            "extract",
            language="rust",
            capability_id_override="custom.capability.id",
        )
    assert result is mock_record


def test_resolve_capability_for_facade_override_not_in_catalog_returns_none() -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.capabilities import CapabilityCatalog
    mock_catalog = MagicMock(spec=CapabilityCatalog)
    mock_catalog.records = []
    mock_runtime = MagicMock()
    mock_runtime.catalog.return_value = mock_catalog

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        result = resolve_capability_for_facade(
            "extract",
            language="rust",
            capability_id_override="unknown.override.id",
        )
    assert result is None


# ---------------------------------------------------------------------------
# apply_workspace_edit_and_checkpoint
# ---------------------------------------------------------------------------


def test_apply_workspace_edit_and_checkpoint_empty_edit_returns_empty_str() -> None:
    result = apply_workspace_edit_and_checkpoint({})
    assert result == ""


def test_apply_workspace_edit_and_checkpoint_empty_changes_returns_empty_str() -> None:
    result = apply_workspace_edit_and_checkpoint({"changes": {}})
    assert result == ""


def test_apply_workspace_edit_and_checkpoint_records_checkpoint(tmp_path: Path) -> None:
    from serena.tools.scalpel_runtime import ScalpelRuntime
    from serena.refactoring.checkpoints import CheckpointStore

    ScalpelRuntime.reset_for_testing()
    store = CheckpointStore()

    f = tmp_path / "check.py"
    f.write_text("before")
    uri = f.as_uri()
    edit = {"changes": {uri: [{
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 6}},
        "newText": "after",
    }]}}

    mock_runtime = MagicMock()
    mock_runtime.checkpoint_store.return_value = store

    with patch.object(ScalpelRuntime, "instance", return_value=mock_runtime):
        cid = apply_workspace_edit_and_checkpoint(edit)

    assert isinstance(cid, str) and cid != ""
    assert f.read_text() == "after"


# ---------------------------------------------------------------------------
# _resolve_winner_edit
# ---------------------------------------------------------------------------


def test_resolve_winner_edit_no_id_attribute() -> None:
    coord = MagicMock()
    action = object()  # no id or action_id attribute
    result = _resolve_winner_edit(coord, action)
    assert result is None


def test_resolve_winner_edit_coord_missing_get_action_edit() -> None:
    coord = object()  # no get_action_edit
    action = MagicMock()
    action.id = "action-1"
    result = _resolve_winner_edit(coord, action)
    assert result is None


def test_resolve_winner_edit_returns_edit_dict() -> None:
    coord = MagicMock()
    expected_edit = {"changes": {"file:///f.py": []}}
    coord.get_action_edit.return_value = expected_edit
    action = MagicMock()
    action.id = "action-1"
    result = _resolve_winner_edit(coord, action)
    assert result == expected_edit


def test_resolve_winner_edit_non_dict_result_returns_none() -> None:
    coord = MagicMock()
    coord.get_action_edit.return_value = "not a dict"
    action = MagicMock()
    action.id = "action-1"
    result = _resolve_winner_edit(coord, action)
    assert result is None
