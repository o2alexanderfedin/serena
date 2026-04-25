"""T1 — TextDocumentEdit applier (basic + multi-edit + version-checked).

Proves: _apply_text_document_edit handles a single TextEdit, multiple TextEdits
on one file, and rejects a TextDocumentEdit whose textDocument.version doesn't
match the LSP-tracked version.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.code_editor import LanguageServerCodeEditor
from solidlsp.ls_utils import TextUtils


class _FakeFileBuffer:
    """Minimal LSPFileBuffer stand-in: reads/writes a string buffer from disk."""

    def __init__(self, abs_path: str, encoding: str) -> None:
        self._abs_path = abs_path
        self._encoding = encoding
        with open(abs_path, encoding=encoding) as f:
            self._contents = f.read()

    @property
    def contents(self) -> str:
        return self._contents

    @contents.setter
    def contents(self, new_contents: str) -> None:
        self._contents = new_contents


class _FakeLanguageServer:
    """Disk-backed fake of SolidLanguageServer for the applier tests.

    Implements only the surface the applier touches:
      - open_file(rel) -> context manager yielding a buffer with `.contents`
      - delete_text_between_positions / insert_text_at_position (called by
        apply_text_edits_to_file)
      - apply_text_edits_to_file (used by EditedFile.apply_text_edits)
      - get_open_file_version (used by the version-check hook)
    """

    def __init__(self, project_root: str, encoding: str) -> None:
        self._project_root = project_root
        self._encoding = encoding
        self._buffers: dict[str, _FakeFileBuffer] = {}
        self._versions: dict[str, int] = {}

    def _abs(self, rel: str) -> str:
        return os.path.join(self._project_root, rel)

    @contextmanager
    def open_file(self, rel: str):
        if rel not in self._buffers:
            self._buffers[rel] = _FakeFileBuffer(self._abs(rel), self._encoding)
        yield self._buffers[rel]

    def get_open_file_version(self, rel: str) -> int | None:
        return self._versions.get(rel)

    def delete_text_between_positions(
        self, rel: str, start_pos: dict[str, Any], end_pos: dict[str, Any]
    ) -> dict[str, Any]:
        with self.open_file(rel) as buf:
            new_contents, _ = TextUtils.delete_text_between_positions(
                buf.contents,
                start_pos["line"],
                start_pos["character"],
                end_pos["line"],
                end_pos["character"],
            )
            buf.contents = new_contents
        return {"line": start_pos["line"], "character": start_pos["character"]}

    def insert_text_at_position(self, rel: str, line: int, col: int, text: str) -> dict[str, Any]:
        with self.open_file(rel) as buf:
            new_contents, end_line, end_col = TextUtils.insert_text_at_position(buf.contents, line, col, text)
            buf.contents = new_contents
        return {"line": end_line, "character": end_col}

    def apply_text_edits_to_file(self, rel: str, edits: list[dict[str, Any]]) -> None:
        with self.open_file(rel):
            sorted_edits = sorted(
                edits,
                key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
                reverse=True,
            )
            for edit in sorted_edits:
                start = edit["range"]["start"]
                end = edit["range"]["end"]
                self.delete_text_between_positions(rel, start, end)
                self.insert_text_at_position(rel, start["line"], start["character"], edit["newText"])


@pytest.fixture
def applier_under_test(tmp_path: Path) -> LanguageServerCodeEditor:
    """Build an applier with a project_root pointing at a tmp dir.

    Uses __new__ to skip __init__ (which requires a full SymbolRetriever);
    we set only the attrs the applier-internal code touches.
    """
    inst = LanguageServerCodeEditor.__new__(LanguageServerCodeEditor)
    inst.project_root = str(tmp_path)
    inst.encoding = "utf-8"
    inst.newline = "\n"
    fake_ls = _FakeLanguageServer(str(tmp_path), "utf-8")
    inst._get_language_server = MagicMock(return_value=fake_ls)  # type: ignore[method-assign]
    return inst


def _write(tmp_path: Path, rel: str, contents: str) -> str:
    p = tmp_path / rel
    p.write_text(contents, encoding="utf-8")
    return p.as_uri()


def test_basic_single_textedit(applier_under_test: LanguageServerCodeEditor, tmp_path: Path) -> None:
    uri = _write(tmp_path, "a.txt", "hello world\n")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": None},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 6},
                            "end": {"line": 0, "character": 11},
                        },
                        "newText": "there",
                    }
                ],
            }
        ]
    }
    n = applier_under_test._apply_workspace_edit(edit)
    assert n == 1
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello there\n"


def test_multi_edit_same_file(applier_under_test: LanguageServerCodeEditor, tmp_path: Path) -> None:
    uri = _write(tmp_path, "b.txt", "alpha beta gamma\n")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
                        "newText": "ALPHA",
                    },
                    {
                        "range": {"start": {"line": 0, "character": 11}, "end": {"line": 0, "character": 16}},
                        "newText": "GAMMA",
                    },
                ],
            }
        ]
    }
    n = applier_under_test._apply_workspace_edit(edit)
    assert n == 1  # one TextDocumentEdit operation
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "ALPHA beta GAMMA\n"


def test_version_mismatch_rejected(applier_under_test: LanguageServerCodeEditor, tmp_path: Path) -> None:
    uri = _write(tmp_path, "c.txt", "x\n")
    # Server tracks version 7; client requests v3 → mismatch.
    fake_ls = applier_under_test._get_language_server.return_value
    fake_ls._versions["c.txt"] = 7

    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": 3},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                        "newText": "Y",
                    }
                ],
            }
        ]
    }
    with pytest.raises(ValueError, match="version mismatch"):
        applier_under_test._apply_workspace_edit(edit)
    # File untouched
    assert (tmp_path / "c.txt").read_text(encoding="utf-8") == "x\n"


def test_version_none_accepted(applier_under_test: LanguageServerCodeEditor, tmp_path: Path) -> None:
    """version=None means client doesn't care; server-tracked version irrelevant."""
    uri = _write(tmp_path, "d.txt", "z\n")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                        "newText": "Z",
                    }
                ],
            }
        ]
    }
    n = applier_under_test._apply_workspace_edit(edit)
    assert n == 1
    assert (tmp_path / "d.txt").read_text(encoding="utf-8") == "Z\n"
