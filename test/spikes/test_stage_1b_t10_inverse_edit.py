"""T10 — inverse_workspace_edit synthesizer."""

from __future__ import annotations

from typing import Any

import pytest

from serena.refactoring.checkpoints import inverse_workspace_edit


def test_inverse_text_document_edit_replaces_full_file() -> None:
    applied: dict[str, Any] = {
        "documentChanges": [
            {
                "textDocument": {"uri": "file:///tmp/a.txt", "version": None},
                "edits": [
                    {
                        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
                        "newText": "WORLD",
                    }
                ],
            }
        ]
    }
    snapshot = {"file:///tmp/a.txt": "hello"}
    inv = inverse_workspace_edit(applied, snapshot)
    changes = inv["documentChanges"]
    assert len(changes) == 1
    assert changes[0]["textDocument"]["uri"] == "file:///tmp/a.txt"
    assert changes[0]["edits"][0]["newText"] == "hello"
    # Inverse uses a full-file replacement; range starts at (0,0) and ends past EOF.
    end = changes[0]["edits"][0]["range"]["end"]
    assert end["line"] >= 0


def test_inverse_create_file_is_delete() -> None:
    applied = {"documentChanges": [{"kind": "create", "uri": "file:///tmp/new.txt"}]}
    snapshot = {"file:///tmp/new.txt": "__NONEXISTENT__"}
    inv = inverse_workspace_edit(applied, snapshot)
    assert inv["documentChanges"] == [{"kind": "delete", "uri": "file:///tmp/new.txt"}]


def test_inverse_delete_file_is_create_plus_textedit() -> None:
    applied = {"documentChanges": [{"kind": "delete", "uri": "file:///tmp/gone.txt"}]}
    snapshot = {"file:///tmp/gone.txt": "the contents\n"}
    inv = inverse_workspace_edit(applied, snapshot)
    chs = inv["documentChanges"]
    assert chs[0] == {"kind": "create", "uri": "file:///tmp/gone.txt", "options": {"overwrite": True}}
    # Then a full-file write of the original content.
    assert chs[1]["textDocument"]["uri"] == "file:///tmp/gone.txt"
    assert chs[1]["edits"][0]["newText"] == "the contents\n"


def test_inverse_rename_file_swaps_uris() -> None:
    applied = {
        "documentChanges": [
            {"kind": "rename", "oldUri": "file:///tmp/a.txt", "newUri": "file:///tmp/b.txt"}
        ]
    }
    inv = inverse_workspace_edit(applied, {})
    assert inv["documentChanges"] == [
        {"kind": "rename", "oldUri": "file:///tmp/b.txt", "newUri": "file:///tmp/a.txt"}
    ]


def test_inverse_mixed_shape_reverses_order() -> None:
    applied = {
        "documentChanges": [
            {"kind": "create", "uri": "file:///tmp/x.txt"},
            {"kind": "rename", "oldUri": "file:///tmp/old.txt", "newUri": "file:///tmp/new.txt"},
            {"kind": "delete", "uri": "file:///tmp/y.txt"},
        ]
    }
    snapshot = {
        "file:///tmp/x.txt": "__NONEXISTENT__",
        "file:///tmp/y.txt": "y-content",
    }
    inv = inverse_workspace_edit(applied, snapshot)
    chs = inv["documentChanges"]
    # Reverse order: delete-inverse first, then rename-inverse, then create-inverse.
    # delete inverse = create + write
    assert chs[0]["kind"] == "create" and chs[0]["uri"] == "file:///tmp/y.txt"
    # rename inverse swaps
    assert chs[2] == {"kind": "rename", "oldUri": "file:///tmp/new.txt", "newUri": "file:///tmp/old.txt"}
    # create inverse = delete
    assert chs[3] == {"kind": "delete", "uri": "file:///tmp/x.txt"}
