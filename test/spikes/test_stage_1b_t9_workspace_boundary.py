"""T9 — workspace-boundary path filter enforces every operation's URI."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.code_editor import LanguageServerCodeEditor, WorkspaceBoundaryError
from solidlsp.ls_utils import TextUtils


class _FakeFileBuffer:
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
    """Minimal disk-backed fake LS for the in-workspace text-edit case."""

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

    def delete_text_between_positions(self, rel: str, start_pos: dict[str, Any], end_pos: dict[str, Any]) -> dict[str, Any]:
        with self.open_file(rel) as buf:
            new_contents, _ = TextUtils.delete_text_between_positions(
                buf.contents, start_pos["line"], start_pos["character"], end_pos["line"], end_pos["character"]
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


def test_in_workspace_text_edit_passes(applier: LanguageServerCodeEditor, tmp_path: Path) -> None:
    target = tmp_path / "in.txt"
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
        ]
    }
    applier._apply_workspace_edit(edit)
    assert target.read_text(encoding="utf-8") == "B\n"


def test_out_of_workspace_create_blocked(applier: LanguageServerCodeEditor, tmp_path: Path, tmp_path_factory) -> None:
    # Use a totally separate tmp tree → guaranteed outside project_root.
    other = tmp_path_factory.mktemp("outside")
    foreign = other / "evil.txt"
    edit: dict[str, Any] = {"documentChanges": [{"kind": "create", "uri": foreign.as_uri()}]}
    with pytest.raises(WorkspaceBoundaryError):
        applier._apply_workspace_edit(edit)
    assert not foreign.exists()


def test_out_of_workspace_delete_blocked(applier: LanguageServerCodeEditor, tmp_path: Path, tmp_path_factory) -> None:
    other = tmp_path_factory.mktemp("outside")
    foreign = other / "victim.txt"
    foreign.write_text("preserved\n", encoding="utf-8")
    edit: dict[str, Any] = {"documentChanges": [{"kind": "delete", "uri": foreign.as_uri()}]}
    with pytest.raises(WorkspaceBoundaryError):
        applier._apply_workspace_edit(edit)
    assert foreign.read_text(encoding="utf-8") == "preserved\n"


def test_out_of_workspace_rename_blocked_on_either_uri(
    applier: LanguageServerCodeEditor, tmp_path: Path, tmp_path_factory
) -> None:
    inside = tmp_path / "in.txt"
    inside.write_text("x\n", encoding="utf-8")
    other = tmp_path_factory.mktemp("outside")
    outside_dst = other / "moved.txt"
    edit: dict[str, Any] = {
        "documentChanges": [
            {"kind": "rename", "oldUri": inside.as_uri(), "newUri": outside_dst.as_uri()}
        ]
    }
    with pytest.raises(WorkspaceBoundaryError):
        applier._apply_workspace_edit(edit)
    assert inside.exists()
    assert not outside_dst.exists()


def test_extra_paths_env_admits_outsider(
    applier: LanguageServerCodeEditor,
    tmp_path: Path,
    tmp_path_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra = tmp_path_factory.mktemp("extra")
    monkeypatch.setenv("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", str(extra))
    target = extra / "ok.txt"
    edit: dict[str, Any] = {"documentChanges": [{"kind": "create", "uri": target.as_uri()}]}
    applier._apply_workspace_edit(edit)
    assert target.exists()


def test_extra_paths_env_pathsep_split(
    applier: LanguageServerCodeEditor,
    tmp_path: Path,
    tmp_path_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = tmp_path_factory.mktemp("ea")
    b = tmp_path_factory.mktemp("eb")
    monkeypatch.setenv("O2_SCALPEL_WORKSPACE_EXTRA_PATHS", f"{a}{os.pathsep}{b}")
    target_b = b / "ok.txt"
    edit: dict[str, Any] = {"documentChanges": [{"kind": "create", "uri": target_b.as_uri()}]}
    applier._apply_workspace_edit(edit)
    assert target_b.exists()
