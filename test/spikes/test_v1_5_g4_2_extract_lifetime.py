"""v1.5 G4-2 — extract_lifetime honors lifetime_name (HI-3).

Acid tests:
  * Caller's lifetime_name flows into title_match.
  * When RA's action title contains the requested lifetime → applied=True;
    real-disk read confirms the new lifetime is in the source.
  * When RA's action picks a different lifetime → response is the G1
    MULTIPLE_CANDIDATES envelope (status=skipped /
    reason=no_candidate_matched_title_match), source is UNCHANGED — not
    silent application of RA's auto-pick.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ExtractLifetimeTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "lib.rs"
    src.write_text("pub struct Holder { name: &str }\n", encoding="utf-8")
    return tmp_path


def _make_tool(project_root: Path) -> ExtractLifetimeTool:
    tool = ExtractLifetimeTool.__new__(ExtractLifetimeTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.is_preferred = False
    a.provenance = "rust-analyzer"
    a.kind = "refactor.extract.extract_lifetime"
    return a


def test_extract_lifetime_honors_named_lifetime(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        # Two candidates; the title-substring filter must select the
        # 'session one (caller's request).
        return [
            _action("ra:1", "Extract lifetime 'a"),
            _action("ra:2", "Extract lifetime 'session"),
        ]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: (
        {"changes": {src.as_uri(): [{
            "range": {"start": {"line": 0, "character": 23},
                      "end": {"line": 0, "character": 24}},
            "newText": "<'session>",
        }]}}
        if aid == "ra:2" else None
    )

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 23},
            lifetime_name="'session",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    assert "'session" in src.read_text(encoding="utf-8")


def test_extract_lifetime_input_not_honored_when_ra_picks_different(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    original = src.read_text(encoding="utf-8")
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return [_action("ra:1", "Extract lifetime 'a")]

    fake_coord.merge_code_actions = _actions

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 23},
            lifetime_name="'session",
            language="rust",
        )
    payload = json.loads(out)
    assert payload.get("status") == "skipped", payload
    assert payload.get("reason") == "no_candidate_matched_title_match"
    # Source unchanged:
    assert src.read_text(encoding="utf-8") == original
