"""T6 - Descending-offset order preservation.

If two TextEdits target the same file, the one at the LATER offset (larger
line, then larger character) must be applied first, otherwise the EARLIER
edit's character delta invalidates the LATER edit's range.

Concrete case: replace 'aaa' (col 0-3) with 'AAAAA' AND replace 'bbb'
(col 4-7) with 'BBB'. If applied col-ascending, the second edit lands at
col 4 of the modified buffer ('AAAAA bbb\\n'), where 'bbb' now starts at
col 6 - the edit hits the space + 'bb' instead. Descending order avoids
this.

T6 pins the contract introduced by T1's pre-sort in
``_apply_text_document_edit`` (code_editor.py around line 391). The
adversarial inputs below would mis-apply if EITHER the production sort
OR the inner ``apply_text_edits_to_file`` sort drifts away from
descending order.
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

    Mirrors the fake used in T1's end-to-end test. ``apply_text_edits_to_file``
    sorts descending internally, matching real SLS behaviour. The T6 contract
    holds when EITHER layer (production pre-sort, inner SLS sort) supplies
    descending ordering; the test fails only if BOTH drift.
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

    # Persist buffers back to disk so the test can read the result via Path.read_text.
    def flush_to_disk(self) -> None:
        for rel, buf in self._buffers.items():
            with open(self._abs(rel), "w", encoding=self._encoding) as f:
                f.write(buf.contents)


@pytest.fixture
def applier(tmp_path: Path) -> LanguageServerCodeEditor:
    inst = LanguageServerCodeEditor.__new__(LanguageServerCodeEditor)
    inst.project_root = str(tmp_path)
    inst.encoding = "utf-8"
    inst.newline = "\n"
    fake_ls = _FakeLanguageServer(str(tmp_path), "utf-8")
    inst._get_language_server = MagicMock(return_value=fake_ls)  # type: ignore[method-assign]
    return inst


def _fake_ls(applier: LanguageServerCodeEditor) -> _FakeLanguageServer:
    return applier._get_language_server.return_value  # type: ignore[no-any-return,attr-defined]


def test_two_same_line_edits_apply_descending(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "ord.txt"
    target.write_text("aaa bbb\n", encoding="utf-8")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": target.as_uri(), "version": None},
                "edits": [
                    # Provided ascending - applier must reorder.
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
                        "newText": "AAAAA",
                    },
                    {
                        "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 7}},
                        "newText": "BBB",
                    },
                ],
            }
        ]
    }
    applier._apply_workspace_edit(edit)
    _fake_ls(applier).flush_to_disk()
    # Correct result if applied descending: "AAAAA BBB\n"
    assert target.read_text(encoding="utf-8") == "AAAAA BBB\n"


def test_multi_line_descending(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "ml.txt"
    target.write_text("line0\nline1\nline2\n", encoding="utf-8")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": target.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
                        "newText": "L0CHANGED",
                    },
                    {
                        "range": {"start": {"line": 2, "character": 0}, "end": {"line": 2, "character": 5}},
                        "newText": "L2CHANGED",
                    },
                ],
            }
        ]
    }
    applier._apply_workspace_edit(edit)
    _fake_ls(applier).flush_to_disk()
    assert target.read_text(encoding="utf-8") == "L0CHANGED\nline1\nL2CHANGED\n"


def test_three_same_line_increasing_columns(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    """Three adversarial single-line edits at strictly increasing column offsets.

    Each replacement changes the buffer length, so any non-descending
    application order would mis-position at least one edit. Provided
    ascending; applier must reorder to descending.
    """
    target = tmp_path / "three.txt"
    target.write_text("aaa bbb ccc\n", encoding="utf-8")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": target.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
                        "newText": "AAAAAAA",  # widens by +4
                    },
                    {
                        "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 7}},
                        "newText": "B",  # shrinks by -2
                    },
                    {
                        "range": {"start": {"line": 0, "character": 8}, "end": {"line": 0, "character": 11}},
                        "newText": "CCCCCC",  # widens by +3
                    },
                ],
            }
        ]
    }
    applier._apply_workspace_edit(edit)
    _fake_ls(applier).flush_to_disk()
    assert target.read_text(encoding="utf-8") == "AAAAAAA B CCCCCC\n"


def test_input_already_descending_unchanged(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    """Input given pre-sorted descending - sort must be stable / idempotent."""
    target = tmp_path / "desc.txt"
    target.write_text("aaa bbb ccc\n", encoding="utf-8")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": target.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 8}, "end": {"line": 0, "character": 11}},
                        "newText": "CCC",
                    },
                    {
                        "range": {"start": {"line": 0, "character": 4}, "end": {"line": 0, "character": 7}},
                        "newText": "BBB",
                    },
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
                        "newText": "AAA",
                    },
                ],
            }
        ]
    }
    applier._apply_workspace_edit(edit)
    _fake_ls(applier).flush_to_disk()
    assert target.read_text(encoding="utf-8") == "AAA BBB CCC\n"


def test_random_interleaved_lines(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    """Edits across multiple lines in shuffled input order (line 1, line 0, line 2)."""
    target = tmp_path / "shuffle.txt"
    target.write_text("aa bb\ncc dd\nee ff\n", encoding="utf-8")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": target.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 2}},
                        "newText": "CCCC",
                    },
                    {
                        "range": {"start": {"line": 0, "character": 3}, "end": {"line": 0, "character": 5}},
                        "newText": "BBBB",
                    },
                    {
                        "range": {"start": {"line": 2, "character": 3}, "end": {"line": 2, "character": 5}},
                        "newText": "FFFF",
                    },
                    {
                        "range": {"start": {"line": 1, "character": 3}, "end": {"line": 1, "character": 5}},
                        "newText": "DDDD",
                    },
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 2}},
                        "newText": "AAAA",
                    },
                    {
                        "range": {"start": {"line": 2, "character": 0}, "end": {"line": 2, "character": 2}},
                        "newText": "EEEE",
                    },
                ],
            }
        ]
    }
    applier._apply_workspace_edit(edit)
    _fake_ls(applier).flush_to_disk()
    assert target.read_text(encoding="utf-8") == "AAAA BBBB\nCCCC DDDD\nEEEE FFFF\n"
