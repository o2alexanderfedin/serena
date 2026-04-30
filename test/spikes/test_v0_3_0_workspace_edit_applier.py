"""v0.3.0 — pure-python WorkspaceEdit applier.

Closes the Stage 3 facade-application gap: the 25 v0.2.0 facades discover
LSP code-actions but record an empty WorkspaceEdit checkpoint without
writing changes to disk. This applier walks an LSP-spec WorkspaceEdit
and applies its TextEdits to the filesystem so facades can mark
``applied=True`` honestly.

Scope:
- Handles the ``changes: {uri: [TextEdit]}`` shape (the dominant pylsp-rope
  + rust-analyzer form).
- Sorts edits within a file by descending position so earlier edits don't
  invalidate later positions.
- ``documentChanges`` (TextDocumentEdit + CreateFile + RenameFile +
  DeleteFile) shape is recognised; resource-creation/rename/delete ops
  land in v1.5 G3b (see ``test_v1_5_g3b_applier_resource_ops.py``).
"""

from __future__ import annotations

from pathlib import Path

from serena.tools.scalpel_facades import _apply_workspace_edit_to_disk


def _file_uri(path: Path) -> str:
    return path.as_uri()


def test_applies_single_text_edit(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("hello world\n")
    edit = {
        "changes": {
            _file_uri(src): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "HELLO",
                }
            ]
        }
    }
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 1
    assert src.read_text(encoding="utf-8") == "HELLO world\n"


def test_applies_multiple_edits_in_descending_order(tmp_path: Path):
    """When two edits land in the same file, they must be applied in
    descending order so the earlier edit doesn't shift the later one."""
    src = tmp_path / "lib.rs"
    src.write_text("aaa bbb ccc\n")
    edit = {
        "changes": {
            _file_uri(src): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 3},
                    },
                    "newText": "AAA",
                },
                {
                    "range": {
                        "start": {"line": 0, "character": 8},
                        "end": {"line": 0, "character": 11},
                    },
                    "newText": "CCC",
                },
            ]
        }
    }
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 2
    assert src.read_text(encoding="utf-8") == "AAA bbb CCC\n"


def test_applies_edits_across_multiple_files(tmp_path: Path):
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("foo\n")
    f2.write_text("bar\n")
    edit = {
        "changes": {
            _file_uri(f1): [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 3}},
                "newText": "FOO",
            }],
            _file_uri(f2): [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 3}},
                "newText": "BAR",
            }],
        }
    }
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 2
    assert f1.read_text(encoding="utf-8") == "FOO\n"
    assert f2.read_text(encoding="utf-8") == "BAR\n"


def test_handles_multi_line_replacement(tmp_path: Path):
    src = tmp_path / "module.py"
    src.write_text("line0\nline1\nline2\nline3\n")
    edit = {
        "changes": {
            _file_uri(src): [{
                "range": {"start": {"line": 1, "character": 0},
                          "end": {"line": 2, "character": 5}},
                "newText": "REPLACED",
            }]
        }
    }
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 1
    assert src.read_text(encoding="utf-8") == "line0\nREPLACED\nline3\n"


def test_handles_pure_insertion_at_end_of_line(tmp_path: Path):
    src = tmp_path / "lib.rs"
    src.write_text("hello\n")
    edit = {
        "changes": {
            _file_uri(src): [{
                "range": {"start": {"line": 0, "character": 5},
                          "end": {"line": 0, "character": 5}},
                "newText": " world",
            }]
        }
    }
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 1
    assert src.read_text(encoding="utf-8") == "hello world\n"


def test_handles_documentchanges_shape(tmp_path: Path):
    """documentChanges is the array form per LSP 3.16+."""
    src = tmp_path / "lib.rs"
    src.write_text("hello\n")
    edit = {
        "documentChanges": [
            {
                "textDocument": {"uri": _file_uri(src), "version": 0},
                "edits": [{
                    "range": {"start": {"line": 0, "character": 0},
                              "end": {"line": 0, "character": 5}},
                    "newText": "HELLO",
                }],
            }
        ]
    }
    count = _apply_workspace_edit_to_disk(edit)
    assert count == 1
    assert src.read_text(encoding="utf-8") == "HELLO\n"


def test_empty_edit_returns_zero_no_op(tmp_path: Path):
    del tmp_path
    assert _apply_workspace_edit_to_disk({}) == 0
    assert _apply_workspace_edit_to_disk({"changes": {}}) == 0
    assert _apply_workspace_edit_to_disk({"documentChanges": []}) == 0


def test_skips_non_file_uris(tmp_path: Path):
    """Anything that isn't a ``file://`` URI is silently skipped."""
    del tmp_path
    edit = {
        "changes": {
            "untitled:Untitled-1": [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 0}},
                "newText": "x",
            }]
        }
    }
    assert _apply_workspace_edit_to_disk(edit) == 0


def test_resource_create_rename_delete_ops_apply_per_lsp_spec(tmp_path: Path):
    """v1.5 G3b lifted the v1.1 deferral: CreateFile / RenameFile /
    DeleteFile now apply per LSP §3.18 (with default options).

    Detailed semantics live in ``test_v1_5_g3b_applier_resource_ops.py``;
    this test guards the high-level "resource ops are no longer dropped
    silently" contract.
    """
    new_uri = (tmp_path / "new.py").as_uri()
    old = tmp_path / "old.py"
    old.write_text("# body\n", encoding="utf-8")
    renamed = tmp_path / "renamed.py"
    edit = {
        "documentChanges": [
            {"kind": "create", "uri": new_uri},
            {"kind": "rename", "oldUri": old.as_uri(), "newUri": renamed.as_uri()},
        ]
    }
    count = _apply_workspace_edit_to_disk(edit)
    # CreateFile + RenameFile both applied:
    assert count == 2
    assert (tmp_path / "new.py").exists()
    assert not old.exists()
    assert renamed.read_text(encoding="utf-8") == "# body\n"


def test_missing_file_returns_zero_no_op(tmp_path: Path):
    """Absent target files are silently no-op'd (defensive; a stale URI
    in a checkpoint shouldn't crash a replay)."""
    edit = {
        "changes": {
            _file_uri(tmp_path / "ghost.py"): [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 0}},
                "newText": "x",
            }]
        }
    }
    assert _apply_workspace_edit_to_disk(edit) == 0
