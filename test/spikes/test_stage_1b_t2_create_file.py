"""T2 — CreateFile applier with option permutations.

Proves: absent target always created; present target without flags errors;
overwrite=True truncates; ignoreIfExists=True silently skips; overwrite
wins over ignoreIfExists when both set.
"""

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


def _create(uri: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    op: dict[str, Any] = {"kind": "create", "uri": uri}
    if options is not None:
        op["options"] = options
    return op


def test_absent_target_creates_empty(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "new.txt"
    edit = {"documentChanges": [_create(target.as_uri())]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""


def test_present_target_no_flags_errors(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "exists.txt"
    target.write_text("keep me\n", encoding="utf-8")
    edit = {"documentChanges": [_create(target.as_uri())]}
    with pytest.raises(FileExistsError):
        applier._apply_workspace_edit(edit)
    # File preserved by atomic restore (T8) — but T2 alone enforces no-op-on-error
    assert target.read_text(encoding="utf-8") == "keep me\n"


def test_present_target_overwrite_truncates(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "to-overwrite.txt"
    target.write_text("old contents\n", encoding="utf-8")
    edit = {"documentChanges": [_create(target.as_uri(), {"overwrite": True})]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert target.read_text(encoding="utf-8") == ""


def test_present_target_ignore_if_exists_skips(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "stable.txt"
    target.write_text("untouched\n", encoding="utf-8")
    edit = {"documentChanges": [_create(target.as_uri(), {"ignoreIfExists": True})]}
    n = applier._apply_workspace_edit(edit)
    assert n == 1  # operation counted as applied (silently skipped)
    assert target.read_text(encoding="utf-8") == "untouched\n"


def test_overwrite_wins_over_ignore_if_exists(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "conflict.txt"
    target.write_text("original\n", encoding="utf-8")
    edit = {
        "documentChanges": [
            _create(target.as_uri(), {"overwrite": True, "ignoreIfExists": True})
        ]
    }
    n = applier._apply_workspace_edit(edit)
    assert n == 1
    assert target.read_text(encoding="utf-8") == ""  # overwrite won
