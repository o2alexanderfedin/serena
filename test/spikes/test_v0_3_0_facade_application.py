"""v0.3.0 — facade-application wire-through.

Verifies that ``_dispatch_single_kind_facade`` (and the per-Python sibling)
now actually apply the resolved WorkspaceEdit to disk via
``_apply_workspace_edit_to_disk``, instead of recording an empty
``{"changes": {}}`` checkpoint as v0.2.0 did.

Backward compatibility: when the fake coordinator doesn't expose
``get_action_edit`` (legacy Stage 3 tests), the dispatcher falls back to
the v0.2.0 empty-checkpoint behavior so existing tests keep passing.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from serena.tools.scalpel_facades import ScalpelChangeVisibilityTool
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def reset_runtime():
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _make_tool(cls, project_root: Path):
    tool = cls.__new__(cls)
    tool.get_project_root = lambda: str(project_root)  # type: ignore[method-assign]
    return tool


def _make_coord_with_edit(action_id: str, kind: str, edit: dict):
    """Fake coord whose merge_code_actions surfaces a winner whose id
    maps to ``edit`` via ``get_action_edit``."""
    coord = MagicMock()
    # v1.5 G4-4 — change_visibility now threads target_visibility into
    # the dispatcher's title_match. The fake's title must contain the
    # tier substring (e.g. "pub") so the dispatcher accepts it.
    winner = MagicMock(
        id=action_id, title="Change visibility to pub",
        kind=kind, provenance="rust-analyzer",
    )

    async def _merge(**kwargs):
        return [winner] if kind in (kwargs.get("only") or []) else []
    coord.merge_code_actions = _merge
    coord.get_action_edit = MagicMock(side_effect=lambda aid: edit if aid == action_id else None)
    return coord


def test_facade_writes_resolved_edit_to_disk(tmp_path: Path):
    """The headline v0.3.0 contract: facade now mutates the file."""
    src = tmp_path / "lib.rs"
    src.write_text("fn private_fn() {}\n")
    expected_after = "pub fn private_fn() {}\n"
    edit = {
        "changes": {
            src.as_uri(): [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 0}},
                "newText": "pub ",
            }]
        }
    }
    tool = _make_tool(ScalpelChangeVisibilityTool, tmp_path)
    coord = _make_coord_with_edit(
        action_id="ra:visibility:1",
        kind="refactor.rewrite.change_visibility",
        edit=edit,
    )
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 3},
            target_visibility="pub", language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["checkpoint_id"]
    # The file must have been mutated.
    assert src.read_text(encoding="utf-8") == expected_after


def test_facade_falls_back_to_empty_checkpoint_when_coord_lacks_lookup(
    tmp_path: Path,
):
    """v0.2.0 backward compat: facades still return applied=True when the
    coord doesn't expose get_action_edit (legacy fakes)."""
    src = tmp_path / "lib.rs"
    src.write_text("fn private_fn() {}\n")
    pre = src.read_text(encoding="utf-8")
    tool = _make_tool(ScalpelChangeVisibilityTool, tmp_path)
    coord = MagicMock()
    # v1.5 G4-4 — title must substring-match target_visibility="pub".
    winner = MagicMock(
        id="ra:legacy:1", title="Change visibility to pub",
        kind="refactor.rewrite.change_visibility",
        provenance="rust-analyzer",
    )

    async def _merge(**kwargs):
        only = kwargs.get("only") or []
        return [winner] if "refactor.rewrite.change_visibility" in only else []
    coord.merge_code_actions = _merge
    # No get_action_edit attribute on this coord.
    del coord.get_action_edit
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 3},
            target_visibility="pub", language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    # Fall-back path: file unchanged because no edit was applied.
    assert src.read_text(encoding="utf-8") == pre


def test_facade_falls_back_when_get_action_edit_returns_none(tmp_path: Path):
    """get_action_edit returning None (untracked id) → empty checkpoint."""
    src = tmp_path / "lib.rs"
    src.write_text("fn x() {}\n")
    pre = src.read_text(encoding="utf-8")
    tool = _make_tool(ScalpelChangeVisibilityTool, tmp_path)
    coord = MagicMock()
    # v1.5 G4-4 — title must substring-match target_visibility="pub".
    winner = MagicMock(
        id="ra:untracked", title="Change visibility to pub",
        kind="refactor.rewrite.change_visibility",
        provenance="rust-analyzer",
    )

    async def _merge(**kwargs):
        return [winner] if "refactor.rewrite.change_visibility" in (kwargs.get("only") or []) else []
    coord.merge_code_actions = _merge
    coord.get_action_edit = MagicMock(return_value=None)
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(src), position={"line": 0, "character": 3},
            target_visibility="pub", language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert src.read_text(encoding="utf-8") == pre


def test_facade_writes_multi_file_edit(tmp_path: Path):
    """Cross-file WorkspaceEdit applies to every referenced file."""
    a = tmp_path / "a.rs"
    b = tmp_path / "b.rs"
    a.write_text("fn original() {}\n")
    b.write_text("use crate::original;\n")
    edit = {
        "changes": {
            a.as_uri(): [{
                "range": {"start": {"line": 0, "character": 3},
                          "end": {"line": 0, "character": 11}},
                "newText": "renamed_",
            }],
            b.as_uri(): [{
                "range": {"start": {"line": 0, "character": 12},
                          "end": {"line": 0, "character": 20}},
                "newText": "renamed_",
            }],
        }
    }
    tool = _make_tool(ScalpelChangeVisibilityTool, tmp_path)
    coord = _make_coord_with_edit(
        action_id="ra:multi:1",
        kind="refactor.rewrite.change_visibility",
        edit=edit,
    )
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=coord,
    ):
        out = tool.apply(
            file=str(a), position={"line": 0, "character": 3},
            target_visibility="pub", language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert "renamed_" in a.read_text(encoding="utf-8")
    assert "renamed_" in b.read_text(encoding="utf-8")
