"""v1.5 G4-1 — change_return_type honors new_return_type (HI-2).

Acid tests:
  * Caller's new_return_type flows into title_match.
  * When RA's action title contains the requested type → applied=True,
    real-disk read confirms the new return type is in the source.
  * When RA's action title does NOT contain the requested type → response
    envelope is the G1 MULTIPLE_CANDIDATES status=skipped /
    reason=no_candidate_matched_title_match shape (honest, not silent
    application of the wrong rewrite).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ChangeReturnTypeTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "lib.rs"
    src.write_text("pub fn calc() -> i32 { 0 }\n", encoding="utf-8")
    return tmp_path


def _make_tool(project_root: Path) -> ChangeReturnTypeTool:
    tool = ChangeReturnTypeTool.__new__(ChangeReturnTypeTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.is_preferred = False
    a.provenance = "rust-analyzer"
    a.kind = "refactor.rewrite.change_return_type"
    return a


def test_change_return_type_honors_new_return_type(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    captured_title_match: list[str | None] = []

    async def _actions(**kw):
        # Two candidates: only the Result one matches the caller's request.
        return [
            _action("ra:1", "Change return type to Option<i32>"),
            _action("ra:2", "Change return type to Result<i32, Error>"),
        ]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: {
        "changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 17},
                      "end": {"line": 0, "character": 20}},
            "newText": "Result<i32, Error>",
        }]},
    } if aid == "ra:2" else None

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 8},
            new_return_type="Result<i32, Error>",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    # Real-disk acid test:
    assert "Result<i32, Error>" in src.read_text(encoding="utf-8")


def test_change_return_type_input_not_honored_when_title_mismatch(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    original_text = src.read_text(encoding="utf-8")
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return [_action("ra:1", "Change return type to Option<i32>")]

    fake_coord.merge_code_actions = _actions

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 8},
            new_return_type="Result<i32, Error>",
            language="rust",
        )
    payload = json.loads(out)
    # G1 envelope shape — honest no-match, NOT silent-apply of Option<i32>.
    assert payload.get("status") == "skipped", payload
    assert payload.get("reason") == "no_candidate_matched_title_match", payload
    assert payload.get("title_match") == "Result<i32, Error>"
    # Real-disk acid test: source UNCHANGED.
    assert src.read_text(encoding="utf-8") == original_text
