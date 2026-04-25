"""T3 — DeleteFile applier with recursive / ignoreIfNotExists option matrix."""

from __future__ import annotations

from pathlib import Path
from typing import Any
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


def _delete(uri: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    op: dict[str, Any] = {"kind": "delete", "uri": uri}
    if options is not None:
        op["options"] = options
    return op


def test_delete_existing_file(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "victim.txt"
    target.write_text("bye\n", encoding="utf-8")
    edit = {"documentChanges": [_delete(target.as_uri())]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert not target.exists()


def test_delete_absent_no_flag_errors(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "nope.txt"
    edit = {"documentChanges": [_delete(target.as_uri())]}
    with pytest.raises(FileNotFoundError):
        applier._apply_workspace_edit(edit)


def test_delete_absent_with_ignore_flag_silent(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "nope.txt"
    edit = {"documentChanges": [_delete(target.as_uri(), {"ignoreIfNotExists": True})]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1


def test_delete_directory_without_recursive_errors(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "subdir"
    target.mkdir()
    (target / "child.txt").write_text("x", encoding="utf-8")
    edit = {"documentChanges": [_delete(target.as_uri())]}
    with pytest.raises(IsADirectoryError):
        applier._apply_workspace_edit(edit)
    assert target.exists()


def test_delete_directory_with_recursive(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "subdir"
    target.mkdir()
    (target / "child.txt").write_text("x", encoding="utf-8")
    edit = {"documentChanges": [_delete(target.as_uri(), {"recursive": True})]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert not target.exists()
