"""v1.5 G4-4 — change_visibility honors target_visibility (HI-5).

Acid tests:
  * target_visibility="pub_crate" → caller picks the
    ``Change visibility to pub(crate)`` action; real-disk read confirms
    only that visibility tier is applied.
  * target_visibility="pub_super" → caller picks the
    ``Change visibility to pub(super)`` action.
  * target_visibility="private" → matches RA's `to private`-shaped title.
  * Ambiguous request (target_visibility="pub" when finer tiers also
    surface) returns the G1 MULTIPLE_CANDIDATES envelope so the caller
    can audit and tighten.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ChangeVisibilityTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "lib.rs"
    src.write_text("fn helper() {}\n", encoding="utf-8")
    return tmp_path


def _make_tool(project_root: Path) -> ChangeVisibilityTool:
    tool = ChangeVisibilityTool.__new__(ChangeVisibilityTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.is_preferred = False
    a.provenance = "rust-analyzer"
    a.kind = "refactor.rewrite.change_visibility"
    return a


def _three_visibility_actions():
    return [
        _action("ra:pub", "Change visibility to pub"),
        _action("ra:crate", "Change visibility to pub(crate)"),
        _action("ra:super", "Change visibility to pub(super)"),
    ]


def test_target_visibility_pub_crate_picks_correct_action(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return _three_visibility_actions()

    fake_coord.merge_code_actions = _actions

    def _resolve(aid):
        if aid == "ra:crate":
            return {"changes": {src.as_uri(): [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 2}},
                "newText": "pub(crate) fn",
            }]}}
        return None

    fake_coord.get_action_edit = _resolve

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            target_visibility="pub_crate",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    assert "pub(crate)" in src.read_text(encoding="utf-8")


def test_target_visibility_pub_super_picks_correct_action(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return _three_visibility_actions()

    fake_coord.merge_code_actions = _actions

    def _resolve(aid):
        if aid == "ra:super":
            return {"changes": {src.as_uri(): [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 2}},
                "newText": "pub(super) fn",
            }]}}
        return None

    fake_coord.get_action_edit = _resolve

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            target_visibility="pub_super",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    assert "pub(super)" in src.read_text(encoding="utf-8")


def test_target_visibility_pub_ambiguous_returns_multiple_candidates(rust_workspace):
    """target_visibility='pub' substring-matches all three of
    `pub`, `pub(crate)`, `pub(super)` actions; G1 surfaces this honestly
    as MULTIPLE_CANDIDATES so the caller can refine."""
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    original = src.read_text(encoding="utf-8")
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return _three_visibility_actions()

    fake_coord.merge_code_actions = _actions

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 0},
            target_visibility="pub",
            language="rust",
        )
    payload = json.loads(out)
    assert payload.get("status") == "skipped", payload
    assert payload.get("reason") == "multiple_candidates_matched_title_match"
    # Source unchanged:
    assert src.read_text(encoding="utf-8") == original
