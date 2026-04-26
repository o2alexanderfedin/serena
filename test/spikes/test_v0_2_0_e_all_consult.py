"""v0.2.0-E — Symbol-path rename consults ``__all__``.

Backlog item #6 from MVP cut. When renaming a Python symbol that appears
in the source file's ``__all__`` list, the rename WorkspaceEdit must also
update the entry so ``from module import *`` continues to expose the
symbol under its new name.
"""

from __future__ import annotations

from pathlib import Path

from serena.tools.scalpel_facades import _augment_workspace_edit_with_all_update


def _empty_edit() -> dict:
    return {"changes": {}}


def test_no_all_in_file_returns_edit_unchanged(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text("def foo(): ...\n")
    edit = _empty_edit()
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(file),
        old_name="foo", new_name="bar",
    )
    assert out == _empty_edit()


def test_all_present_but_old_name_absent_returns_edit_unchanged(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text('__all__ = ["other"]\ndef foo(): ...\n')
    edit = _empty_edit()
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(file),
        old_name="foo", new_name="bar",
    )
    assert out == _empty_edit()


def test_all_contains_old_name_appends_text_edit(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text('__all__ = ["foo"]\ndef foo(): ...\n')
    edit = _empty_edit()
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(file),
        old_name="foo", new_name="bar",
    )
    file_uri = file.as_uri()
    assert file_uri in out["changes"]
    text_edits = out["changes"][file_uri]
    assert len(text_edits) == 1
    te = text_edits[0]
    assert te["newText"] == "bar"
    # The literal "foo" at line 0, characters 12-15 (between the quotes).
    assert te["range"]["start"] == {"line": 0, "character": 12}
    assert te["range"]["end"] == {"line": 0, "character": 15}


def test_all_with_multiple_entries_only_updates_old_name(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text('__all__ = ["alpha", "foo", "beta"]\n')
    edit = _empty_edit()
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(file),
        old_name="foo", new_name="bar",
    )
    text_edits = out["changes"][file.as_uri()]
    assert len(text_edits) == 1
    te = text_edits[0]
    assert te["newText"] == "bar"


def test_all_as_tuple_form(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text('__all__ = ("foo",)\n')
    edit = _empty_edit()
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(file),
        old_name="foo", new_name="bar",
    )
    text_edits = out["changes"][file.as_uri()]
    assert len(text_edits) == 1


def test_all_multiline_literal(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text(
        '__all__ = [\n'
        '    "alpha",\n'
        '    "foo",\n'
        '    "beta",\n'
        ']\n'
    )
    edit = _empty_edit()
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(file),
        old_name="foo", new_name="bar",
    )
    text_edits = out["changes"][file.as_uri()]
    assert len(text_edits) == 1
    te = text_edits[0]
    # "foo" is on line 2 (0-indexed), inside the quotes at col 5..8.
    assert te["range"]["start"]["line"] == 2
    assert te["range"]["end"]["line"] == 2
    assert te["newText"] == "bar"


def test_appends_to_existing_file_edits_in_workspace_edit(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text('__all__ = ["foo"]\n')
    file_uri = file.as_uri()
    pre_existing = {
        "range": {
            "start": {"line": 1, "character": 0},
            "end": {"line": 1, "character": 3},
        },
        "newText": "bar",
    }
    edit = {"changes": {file_uri: [pre_existing]}}
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(file),
        old_name="foo", new_name="bar",
    )
    text_edits = out["changes"][file_uri]
    assert len(text_edits) == 2
    assert pre_existing in text_edits


def test_invalid_python_returns_edit_unchanged(tmp_path: Path):
    file = tmp_path / "module.py"
    file.write_text('def foo(\n')  # SyntaxError
    edit = _empty_edit()
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(file),
        old_name="foo", new_name="bar",
    )
    assert out == _empty_edit()


def test_unreadable_file_returns_edit_unchanged(tmp_path: Path):
    edit = _empty_edit()
    out = _augment_workspace_edit_with_all_update(
        workspace_edit=edit, file=str(tmp_path / "missing.py"),
        old_name="foo", new_name="bar",
    )
    assert out == _empty_edit()
