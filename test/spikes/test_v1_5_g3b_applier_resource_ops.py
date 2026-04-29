"""v1.5 G3b — _apply_workspace_edit_to_disk resource-op support (CR-2).

Acid tests:
  * CreateFile creates a missing file (empty) and mkdir -p the parent.
  * CreateFile with options.ignoreIfExists=True (default) → no-op when
    file already exists.
  * CreateFile with options.overwrite=True replaces existing content.
  * RenameFile moves the file; options.overwrite=False (default) +
    target exists → no rename, no exception (LSP semantics).
  * RenameFile with options.overwrite=True replaces target.
  * DeleteFile removes the file; options.ignoreIfNotExists=True (default)
    + missing file → no-op.
  * Mixed edit (CreateFile + TextDocumentEdit on the new file) applies
    both ops in order; final read_text() contains the inserted body.

Every assertion is via Path.read_text() / Path.exists() — no mocks for
the filesystem layer.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from serena.tools.scalpel_facades import _apply_workspace_edit_to_disk


def _file_uri(p: Path) -> str:
    return p.as_uri()


def test_create_file_writes_empty_when_absent(tmp_path: Path):
    target = tmp_path / "subdir" / "new.rs"
    edit = {
        "documentChanges": [
            {"kind": "create", "uri": _file_uri(target)},
        ]
    }
    count = _apply_workspace_edit_to_disk(edit)
    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""
    assert count >= 1


def test_create_file_default_ignores_existing(tmp_path: Path):
    target = tmp_path / "exists.rs"
    target.write_text("// preserved\n", encoding="utf-8")
    edit = {"documentChanges": [
        {"kind": "create", "uri": _file_uri(target)},
    ]}
    _apply_workspace_edit_to_disk(edit)
    # ignoreIfExists is the LSP default — content preserved.
    assert target.read_text(encoding="utf-8") == "// preserved\n"


def test_create_file_overwrite_replaces_existing(tmp_path: Path):
    target = tmp_path / "exists.rs"
    target.write_text("// old\n", encoding="utf-8")
    edit = {"documentChanges": [
        {"kind": "create", "uri": _file_uri(target),
         "options": {"overwrite": True}},
    ]}
    _apply_workspace_edit_to_disk(edit)
    assert target.read_text(encoding="utf-8") == ""


def test_rename_file_moves_when_target_absent(tmp_path: Path):
    src = tmp_path / "old.rs"
    dst = tmp_path / "new.rs"
    src.write_text("// body\n", encoding="utf-8")
    edit = {"documentChanges": [
        {"kind": "rename", "oldUri": _file_uri(src), "newUri": _file_uri(dst)},
    ]}
    _apply_workspace_edit_to_disk(edit)
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "// body\n"


def test_rename_file_default_no_overwrite_when_target_exists(tmp_path: Path):
    src = tmp_path / "old.rs"
    dst = tmp_path / "new.rs"
    src.write_text("// from\n", encoding="utf-8")
    dst.write_text("// to\n", encoding="utf-8")
    edit = {"documentChanges": [
        {"kind": "rename", "oldUri": _file_uri(src), "newUri": _file_uri(dst)},
    ]}
    # LSP default: overwrite=False, ignoreIfExists=False → MUST NOT silently
    # clobber. The applier elects to skip (no exception, count not incremented).
    _apply_workspace_edit_to_disk(edit)
    # Source preserved (rename was a no-op):
    assert src.read_text(encoding="utf-8") == "// from\n"
    assert dst.read_text(encoding="utf-8") == "// to\n"


def test_rename_file_overwrite_replaces_target(tmp_path: Path):
    src = tmp_path / "old.rs"
    dst = tmp_path / "new.rs"
    src.write_text("// from\n", encoding="utf-8")
    dst.write_text("// to\n", encoding="utf-8")
    edit = {"documentChanges": [
        {"kind": "rename", "oldUri": _file_uri(src), "newUri": _file_uri(dst),
         "options": {"overwrite": True}},
    ]}
    _apply_workspace_edit_to_disk(edit)
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "// from\n"


def test_delete_file_removes_when_present(tmp_path: Path):
    target = tmp_path / "doomed.rs"
    target.write_text("// rip\n", encoding="utf-8")
    edit = {"documentChanges": [
        {"kind": "delete", "uri": _file_uri(target)},
    ]}
    _apply_workspace_edit_to_disk(edit)
    assert not target.exists()


def test_delete_file_default_ignores_missing(tmp_path: Path):
    target = tmp_path / "ghost.rs"
    edit = {"documentChanges": [
        {"kind": "delete", "uri": _file_uri(target)},
    ]}
    # LSP default: ignoreIfNotExists=True; no-op + no exception.
    _apply_workspace_edit_to_disk(edit)
    assert not target.exists()


def test_create_then_text_edit_in_same_workspace_edit(tmp_path: Path):
    target = tmp_path / "new.rs"
    edit = {"documentChanges": [
        {"kind": "create", "uri": _file_uri(target)},
        {"textDocument": {"uri": _file_uri(target), "version": None},
         "edits": [{"range": {"start": {"line": 0, "character": 0},
                              "end": {"line": 0, "character": 0}},
                    "newText": "pub fn moved() {}\n"}]},
    ]}
    _apply_workspace_edit_to_disk(edit)
    assert target.read_text(encoding="utf-8") == "pub fn moved() {}\n"


def test_unknown_kind_is_skipped_for_forward_compat(tmp_path: Path):
    """Future LSP resource-op kinds must not crash the applier."""
    target = tmp_path / "would_be.rs"
    edit = {"documentChanges": [
        {"kind": "future_unknown_op", "uri": _file_uri(target)},
    ]}
    # No exception, no creation:
    _apply_workspace_edit_to_disk(edit)
    assert not target.exists()


def test_rename_file_missing_source_is_skipped(tmp_path: Path):
    """If oldUri does not exist, rename is a silent no-op."""
    src = tmp_path / "missing.rs"
    dst = tmp_path / "target.rs"
    edit = {"documentChanges": [
        {"kind": "rename", "oldUri": _file_uri(src), "newUri": _file_uri(dst)},
    ]}
    _apply_workspace_edit_to_disk(edit)
    assert not src.exists()
    assert not dst.exists()
