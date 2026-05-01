"""T5 — SnippetTextEdit defensive $N / ${N marker stripping."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
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

    Mirrors the fake used in T1's end-to-end test so the snippet stripper
    can be exercised through ``_apply_workspace_edit``.
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
def applier(tmp_path: Path) -> LanguageServerCodeEditor:
    inst = LanguageServerCodeEditor.__new__(LanguageServerCodeEditor)
    inst.project_root = str(tmp_path)
    inst.encoding = "utf-8"
    inst.newline = "\n"
    fake_ls = _FakeLanguageServer(str(tmp_path), "utf-8")
    inst._get_language_server = MagicMock(return_value=fake_ls)  # type: ignore[method-assign]
    return inst


def test_strip_dollar_n(applier: LanguageServerCodeEditor) -> None:
    assert applier._strip_snippet_markers("foo$0bar") == "foobar"
    assert applier._strip_snippet_markers("$1$2$3$0") == ""


def test_strip_dollar_brace_n(applier: LanguageServerCodeEditor) -> None:
    assert applier._strip_snippet_markers("foo${1:bar}baz") == "foobarbaz"
    assert applier._strip_snippet_markers("${0}end") == "end"
    assert applier._strip_snippet_markers("hello${2:world${1:nested}}!") == "helloworldnested!"


def test_strip_preserves_literal_dollar(applier: LanguageServerCodeEditor) -> None:
    """Literal $ must be escaped as ``\\$`` per LSP grammar.

    Per the plan's TDD edge-case note: ``$N`` is always a placeholder in LSP
    snippet grammar, so an unescaped ``$5`` is correctly stripped. To preserve
    a literal dollar sign in code, conformant servers emit ``\\$`` — this test
    pins the escaped-dollar pathway (per plan line 1327).
    """
    assert applier._strip_snippet_markers("price: \\$5.00") == "price: $5.00"


def test_strip_escaped_dollar(applier: LanguageServerCodeEditor) -> None:
    """Escaped \\$ stays as $ (LSP snippet grammar)."""
    assert applier._strip_snippet_markers("\\$0kept") == "$0kept"


def test_defang_text_edit_strips_newtext(applier: LanguageServerCodeEditor) -> None:
    te = {
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
        "newText": "fn$0()",
    }
    out = applier._defang_text_edit(te)
    assert out["newText"] == "fn()"
    assert out["range"] == te["range"]


def test_end_to_end_strip_in_workspace_edit(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "snippet.txt"
    target.write_text("xyz\n", encoding="utf-8")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": target.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
                        "newText": "abc${0}",
                    }
                ],
            }
        ]
    }
    applier._apply_workspace_edit(cast(Any, edit))
    assert target.read_text(encoding="utf-8") == "abc\n"
