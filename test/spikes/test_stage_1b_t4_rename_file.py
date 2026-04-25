"""T4 — RenameFile applier with overwrite / ignoreIfExists permutations."""

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


def _rename(old_uri: str, new_uri: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    op: dict[str, Any] = {"kind": "rename", "oldUri": old_uri, "newUri": new_uri}
    if options is not None:
        op["options"] = options
    return op


def test_basic_rename(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    src = tmp_path / "old.txt"
    dst = tmp_path / "new.txt"
    src.write_text("payload\n", encoding="utf-8")
    edit = {"documentChanges": [_rename(src.as_uri(), dst.as_uri())]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "payload\n"


def test_rename_dst_exists_no_flag_errors(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    src = tmp_path / "old.txt"
    dst = tmp_path / "new.txt"
    src.write_text("a", encoding="utf-8")
    dst.write_text("b", encoding="utf-8")
    edit = {"documentChanges": [_rename(src.as_uri(), dst.as_uri())]}
    with pytest.raises(FileExistsError):
        applier._apply_workspace_edit(edit)
    assert src.exists() and dst.exists()


def test_rename_dst_exists_overwrite(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    src = tmp_path / "old.txt"
    dst = tmp_path / "new.txt"
    src.write_text("WIN\n", encoding="utf-8")
    dst.write_text("LOSE\n", encoding="utf-8")
    edit = {"documentChanges": [_rename(src.as_uri(), dst.as_uri(), {"overwrite": True})]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "WIN\n"


def test_rename_dst_exists_ignore_if_exists_skips(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    src = tmp_path / "old.txt"
    dst = tmp_path / "new.txt"
    src.write_text("alive\n", encoding="utf-8")
    dst.write_text("untouched\n", encoding="utf-8")
    edit = {"documentChanges": [_rename(src.as_uri(), dst.as_uri(), {"ignoreIfExists": True})]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert src.read_text(encoding="utf-8") == "alive\n"
    assert dst.read_text(encoding="utf-8") == "untouched\n"


def test_rename_overwrite_wins_over_ignore_if_exists(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    src = tmp_path / "old.txt"
    dst = tmp_path / "new.txt"
    src.write_text("WIN\n", encoding="utf-8")
    dst.write_text("LOSE\n", encoding="utf-8")
    edit = {
        "documentChanges": [
            _rename(src.as_uri(), dst.as_uri(), {"overwrite": True, "ignoreIfExists": True})
        ]
    }
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert dst.read_text(encoding="utf-8") == "WIN\n"
