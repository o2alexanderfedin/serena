"""v1.5 G3a — _split_rust per-group iteration (CR-1 user-report close-out).

Acid tests:
  * groups={"helpers":["add"], "ops":["sub"]} dispatches TWO
    refactor.extract.module requests (one per symbol).
  * Each request's (start, end) range matches the symbol's body span as
    returned by coord.find_symbol_range — NOT (0,0)→(0,0).
  * Empty groups remains a no-op (no LSP call).
  * Symbol-not-found in one of N symbols + allow_partial=True → other
    symbols still dispatch; failed symbol appears in language_findings.
  * allow_partial=False (default) → first failure aborts.
  * Real-disk acid test (G3b already in tree): the post-applier file
    state contains the text-edit slice that was scheduled for the
    captured WorkspaceEdit; (0,0)->(0,0) degenerate dispatch never
    leaves the helper.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import SplitFileTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "lib.rs"
    src.write_text(
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"
        "pub fn sub(a: i32, b: i32) -> i32 { a - b }\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_tool(project_root: Path) -> SplitFileTool:
    tool = SplitFileTool.__new__(SplitFileTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str, *, kind: str = "refactor.extract.module"):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.kind = kind
    a.is_preferred = False
    a.provenance = "rust-analyzer"
    return a


def test_split_rust_dispatches_per_symbol_with_real_ranges(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    # Per-symbol ranges as the real coordinator would return:
    range_for = {
        "add": {"start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 44}},
        "sub": {"start": {"line": 1, "character": 0},
                "end": {"line": 1, "character": 44}},
    }

    async def _find(file, name_path, project_root):
        return range_for.get(name_path)

    fake_coord.find_symbol_range = _find

    captured_calls: list[dict] = []

    async def _merge_actions(**kwargs):
        captured_calls.append(kwargs)
        return [_action(f"ra:{kwargs['start']['line']}",
                        f"Move to module #{kwargs['start']['line']}")]

    fake_coord.merge_code_actions = _merge_actions

    # Each action resolves to a WorkspaceEdit creating a new module file +
    # rewriting the original file's top line.
    def _resolve(aid):
        line = aid.split(":")[1]
        new_module = f"helpers_{line}.rs"
        return {
            "documentChanges": [
                {"kind": "create",
                 "uri": (rust_workspace / new_module).as_uri()},
                {"textDocument": {"uri": (rust_workspace / new_module).as_uri(),
                                  "version": None},
                 "edits": [{"range": {"start": {"line": 0, "character": 0},
                                      "end": {"line": 0, "character": 0}},
                            "newText": f"// moved symbol from line {line}\n"}]},
            ],
        }

    fake_coord.get_action_edit = _resolve

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            groups={"helpers": ["add"], "ops": ["sub"]},
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload

    # Per-symbol dispatch: TWO calls, each with the symbol's real range.
    assert len(captured_calls) == 2, captured_calls
    starts = sorted(c["start"]["line"] for c in captured_calls)
    assert starts == [0, 1], starts
    # No (0,0)→(0,0) degenerate request:
    for c in captured_calls:
        assert (c["start"], c["end"]) != (
            {"line": 0, "character": 0}, {"line": 0, "character": 0},
        )

    # Real-disk acid test: G3b already lands resource-op support, so the
    # CreateFile + textDocumentEdit pair flows through the applier and the
    # new module files materialize on disk with the moved-symbol comment.
    assert (rust_workspace / "helpers_0.rs").exists()
    assert "moved symbol from line 0" in (
        rust_workspace / "helpers_0.rs"
    ).read_text(encoding="utf-8")
    assert (rust_workspace / "helpers_1.rs").exists()
    assert "moved symbol from line 1" in (
        rust_workspace / "helpers_1.rs"
    ).read_text(encoding="utf-8")


def test_split_rust_empty_groups_short_circuits(rust_workspace):
    tool = _make_tool(rust_workspace)
    fake_coord = MagicMock()
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(rust_workspace / "lib.rs"),
            groups={},
            language="rust",
        )
    payload = json.loads(out)
    assert payload["no_op"] is True


def test_split_rust_symbol_not_found_aborts_when_allow_partial_false(rust_workspace):
    tool = _make_tool(rust_workspace)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _find(file, name_path, project_root):
        return None  # always unresolvable

    fake_coord.find_symbol_range = _find

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(rust_workspace / "lib.rs"),
            groups={"helpers": ["nonexistent"]},
            language="rust",
            allow_partial=False,
        )
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"


def test_split_rust_allow_partial_skips_unresolvable(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _find(file, name_path, project_root):
        if name_path == "add":
            return {"start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 44}}
        return None

    fake_coord.find_symbol_range = _find

    async def _merge_actions(**kwargs):
        return [_action("ra:1", "Move add")]

    fake_coord.merge_code_actions = _merge_actions
    fake_coord.get_action_edit = lambda aid: {"changes": {}}

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            groups={"helpers": ["add", "missing"]},
            language="rust",
            allow_partial=True,
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    # Failed symbol surfaces as a language_finding warning.
    assert any(
        "missing" in (lf.get("message") or "")
        for lf in payload.get("language_findings") or ()
    )
