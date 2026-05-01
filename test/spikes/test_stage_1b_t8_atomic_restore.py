"""T8 - atomic snapshot + restore on partial failure."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from serena.code_editor import LanguageServerCodeEditor


@pytest.fixture
def applier(tmp_path: Path) -> LanguageServerCodeEditor:
    inst = LanguageServerCodeEditor.__new__(LanguageServerCodeEditor)
    inst.project_root = str(tmp_path)
    inst.encoding = "utf-8"
    inst.newline = "\n"
    inst._get_language_server = MagicMock()  # type: ignore[method-assign]
    return inst


def test_first_succeeds_second_fails_restores_first(
    applier: LanguageServerCodeEditor, tmp_path: Path
) -> None:
    """Two TextDocumentEdits: first OK, second targets unwriteable path -> both reverted."""
    a = tmp_path / "a.txt"
    a.write_text("ORIGINAL_A\n", encoding="utf-8")
    # Path with no parent dir + no write perms - but easier: target a path whose
    # parent is a *file*, which makes the open() fail.
    blocker = tmp_path / "blocker"
    blocker.write_text("not-a-dir\n", encoding="utf-8")
    bad = tmp_path / "blocker" / "child.txt"  # parent is a file -> ENOTDIR

    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": a.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 10}},
                        "newText": "MUTATED_A",
                    }
                ],
            },
            {"kind": "create", "uri": bad.as_uri()},
        ]
    }
    with pytest.raises(Exception):
        applier._apply_workspace_edit(cast(Any, edit))
    # File a must be restored.
    assert a.read_text(encoding="utf-8") == "ORIGINAL_A\n"


def test_create_then_failure_deletes_created(
    applier: LanguageServerCodeEditor, tmp_path: Path
) -> None:
    """CreateFile then a TextDocumentEdit that fails (version mismatch) -> created file deleted."""
    new_file = tmp_path / "fresh.txt"
    other = tmp_path / "other.txt"
    other.write_text("orig\n", encoding="utf-8")

    fake_ls = MagicMock()
    fake_ls.get_open_file_version.return_value = 99
    cast(Any, applier._get_language_server).return_value = fake_ls

    edit: dict[str, Any] = {
        "documentChanges": [
            {"kind": "create", "uri": new_file.as_uri()},
            {
                "textDocument": {"uri": other.as_uri(), "version": 1},  # mismatch!
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 4}},
                        "newText": "MUT",
                    }
                ],
            },
        ]
    }
    with pytest.raises(ValueError, match="version mismatch"):
        applier._apply_workspace_edit(cast(Any, edit))
    # The created file must have been removed by restore.
    assert not new_file.exists()
    # The other file must be untouched.
    assert other.read_text(encoding="utf-8") == "orig\n"


def test_delete_then_failure_recreates_deleted(
    applier: LanguageServerCodeEditor, tmp_path: Path
) -> None:
    """DeleteFile then a CreateFile collision -> deleted file restored."""
    deletable = tmp_path / "del.txt"
    deletable.write_text("PRESERVED\n", encoding="utf-8")
    blocker = tmp_path / "block"
    blocker.write_text("present\n", encoding="utf-8")

    edit: dict[str, Any] = {
        "documentChanges": [
            {"kind": "delete", "uri": deletable.as_uri()},
            {"kind": "create", "uri": blocker.as_uri()},  # no overwrite, no ignore -> error
        ]
    }
    with pytest.raises(FileExistsError):
        applier._apply_workspace_edit(cast(Any, edit))
    assert deletable.read_text(encoding="utf-8") == "PRESERVED\n"
