"""v1.5 G4-3 — generate_trait_impl_scaffold honors trait_name (HI-4).

Acid tests:
  * Caller's trait_name (REQUIRED positional arg) flows into title_match.
  * When RA offers actions for multiple candidate traits, the title-match
    selects the requested one; real-disk read confirms only that trait
    is scaffolded.
  * When the requested trait is not among RA's candidates, the response
    is the G1 MULTIPLE_CANDIDATES envelope and the source is UNCHANGED
    (no silent scaffold of the wrong trait).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import GenerateTraitImplScaffoldTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


@pytest.fixture
def rust_workspace(tmp_path: Path) -> Path:
    src = tmp_path / "lib.rs"
    src.write_text("pub struct Foo;\n", encoding="utf-8")
    return tmp_path


def _make_tool(project_root: Path) -> GenerateTraitImplScaffoldTool:
    tool = GenerateTraitImplScaffoldTool.__new__(GenerateTraitImplScaffoldTool)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _action(action_id: str, title: str):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.is_preferred = False
    a.provenance = "rust-analyzer"
    a.kind = "refactor.rewrite.generate_trait_impl"
    return a


def test_generate_trait_impl_honors_named_trait(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return [
            _action("ra:1", "Implement Debug for Foo"),
            _action("ra:2", "Implement Display for Foo"),
        ]

    fake_coord.merge_code_actions = _actions
    fake_coord.get_action_edit = lambda aid: (
        {"changes": {src.as_uri(): [{
            "range": {"start": {"line": 1, "character": 0},
                      "end": {"line": 1, "character": 0}},
            "newText": ("impl Display for Foo {\n"
                        "    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {\n"
                        "        todo!()\n    }\n}\n"),
        }]}}
        if aid == "ra:2" else None
    )

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 12},
            trait_name="Display",
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True, payload
    body = src.read_text(encoding="utf-8")
    assert "impl Display for Foo" in body
    assert "impl Debug" not in body


def test_generate_trait_impl_input_not_honored_when_unknown_trait(rust_workspace):
    tool = _make_tool(rust_workspace)
    src = rust_workspace / "lib.rs"
    original = src.read_text(encoding="utf-8")
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _actions(**kw):
        return [_action("ra:1", "Implement Debug for Foo")]

    fake_coord.merge_code_actions = _actions

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(src),
            position={"line": 0, "character": 12},
            trait_name="Display",
            language="rust",
        )
    payload = json.loads(out)
    assert payload.get("status") == "skipped", payload
    assert payload.get("reason") == "no_candidate_matched_title_match"
    assert src.read_text(encoding="utf-8") == original
