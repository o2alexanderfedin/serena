"""T7 - changeAnnotations advisory surfacer.

Proves: applier collects the changeAnnotations map and exposes it via the
result; needsConfirmation=True does NOT block the apply (caller's policy).
"""

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

    Reused pattern from T1/T6. ``apply_text_edits_to_file`` sorts descending
    internally, matching real SLS behaviour.
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
    return cast(Any, applier._get_language_server).return_value  # type: ignore[no-any-return,attr-defined]


def test_collect_change_annotations_returns_map(applier: LanguageServerCodeEditor) -> None:
    edit: dict[str, Any] = {
        "documentChanges": [],
        "changeAnnotations": {
            "rename-shadowing": {
                "label": "Rename may shadow",
                "needsConfirmation": True,
                "description": "Local variable shadows module-level name",
            },
            "safe-rename": {
                "label": "Safe rename",
            },
        },
    }
    out = applier._collect_change_annotations(edit)
    assert "rename-shadowing" in out
    assert out["rename-shadowing"]["needsConfirmation"] is True
    assert out["safe-rename"]["label"] == "Safe rename"


def test_collect_returns_empty_when_absent(applier: LanguageServerCodeEditor) -> None:
    assert applier._collect_change_annotations({"documentChanges": []}) == {}


def test_apply_does_not_block_on_needs_confirmation(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("a\n", encoding="utf-8")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": target.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                        "newText": "B",
                    }
                ],
            }
        ],
        "changeAnnotations": {
            "any-id": {"label": "scary", "needsConfirmation": True},
        },
    }
    n = applier._apply_workspace_edit(cast(Any, edit))
    _fake_ls(applier).flush_to_disk()
    assert n == 1
    assert target.read_text(encoding="utf-8") == "B\n"


def test_apply_workspace_edit_with_report_returns_annotations(
    applier: LanguageServerCodeEditor, tmp_path: Path
) -> None:
    target = tmp_path / "g.txt"
    target.write_text("x\n", encoding="utf-8")
    edit: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": target.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                        "newText": "Y",
                    }
                ],
            }
        ],
        "changeAnnotations": {
            "id1": {"label": "L1"},
        },
    }
    report = applier._apply_workspace_edit_with_report(cast(Any, edit))
    assert report["count"] == 1
    assert report["annotations"] == {"id1": {"label": "L1"}}
    assert isinstance(report["snapshot"], dict)
