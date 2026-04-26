"""T6 — merge_code_actions composes broadcast + resolve + priority + dedup."""

from __future__ import annotations

import pytest

from serena.refactoring.multi_server import (
    MergedCodeAction,
    MultiServerCoordinator,
)


def _edit_dc(uri: str, sl: int, sc: int, el: int, ec: int, txt: str) -> dict:
    return {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": None},
                "edits": [
                    {"range": {"start": {"line": sl, "character": sc}, "end": {"line": el, "character": ec}}, "newText": txt}
                ],
            }
        ]
    }


@pytest.mark.asyncio
async def test_organize_imports_ruff_wins_pylsp_rope_dropped(fake_pool):
    """P2 finding: ruff publishes source.organizeImports.ruff; pylsp-rope
    publishes bare source.organizeImports. _normalize_kind collapses both
    onto the same family; _apply_priority keeps ruff."""
    fake_pool["ruff"].code_actions = [
        {"title": "Organize imports", "kind": "source.organizeImports.ruff",
         "edit": _edit_dc("file:///x.py", 0, 0, 3, 0, "")}
    ]
    fake_pool["pylsp-rope"].code_actions = [
        {"title": "Organize imports", "kind": "source.organizeImports",
         "edit": _edit_dc("file:///x.py", 0, 0, 3, 0, "")}
    ]
    fake_pool["basedpyright"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["source.organizeImports"],
    )
    assert len(merged) == 1
    assert merged[0].provenance == "ruff"
    assert merged[0].kind == "source.organizeImports.ruff"


@pytest.mark.asyncio
async def test_resolve_called_for_deferred_actions(fake_pool):
    """When a candidate lacks both ``edit`` and ``command``, the merger
    issues codeAction/resolve to populate it before classification."""
    deferred = {"title": "Quick fix", "kind": "quickfix", "data": {"id": "qf-1"}}
    resolved = {**deferred, "edit": _edit_dc("file:///x.py", 0, 0, 0, 5, "fix")}
    fake_pool["pylsp-rope"].code_actions = [deferred]
    fake_pool["pylsp-rope"].resolve_map = {"qf-1": resolved}
    fake_pool["basedpyright"].code_actions = []
    fake_pool["ruff"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["quickfix"],
    )
    assert len(merged) == 1
    assert merged[0].provenance == "pylsp-rope"
    # The presence of an edit on the merged action proves resolve fired.
    assert any(c[0] == "resolve_code_action" for c in fake_pool["pylsp-rope"].calls)


@pytest.mark.asyncio
async def test_resolve_skipped_for_command_typed_actions(fake_pool):
    """pylsp-rope ships command-typed actions (P1 finding) — no
    resolve needed because the command is the actionable payload."""
    cmd_typed = {"title": "Run extract", "kind": "refactor.extract",
                 "command": {"title": "Extract", "command": "pylsp_rope.extract"}}
    fake_pool["pylsp-rope"].code_actions = [cmd_typed]
    fake_pool["basedpyright"].code_actions = []
    fake_pool["ruff"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["refactor.extract"],
    )
    assert len(merged) == 1
    assert merged[0].provenance == "pylsp-rope"
    assert not any(c[0] == "resolve_code_action" for c in fake_pool["pylsp-rope"].calls)


@pytest.mark.asyncio
async def test_suppressed_alternatives_attached_when_debug_merge_set(fake_pool, monkeypatch):
    """§11.4 — suppressed_alternatives populates only when
    O2_SCALPEL_DEBUG_MERGE=1."""
    monkeypatch.setenv("O2_SCALPEL_DEBUG_MERGE", "1")
    fake_pool["ruff"].code_actions = [
        {"title": "Organize imports", "kind": "source.organizeImports.ruff",
         "edit": _edit_dc("file:///x.py", 0, 0, 3, 0, "")}
    ]
    fake_pool["pylsp-rope"].code_actions = [
        {"title": "Organize imports", "kind": "source.organizeImports",
         "edit": _edit_dc("file:///x.py", 0, 0, 3, 0, "")}
    ]
    fake_pool["basedpyright"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["source.organizeImports"],
    )
    assert len(merged) == 1
    assert merged[0].provenance == "ruff"
    sup_provs = {s.provenance for s in merged[0].suppressed_alternatives}
    assert "pylsp-rope" in sup_provs


@pytest.mark.asyncio
async def test_suppressed_alternatives_empty_when_debug_merge_unset(fake_pool, monkeypatch):
    monkeypatch.delenv("O2_SCALPEL_DEBUG_MERGE", raising=False)
    fake_pool["ruff"].code_actions = [
        {"title": "Organize imports", "kind": "source.organizeImports.ruff",
         "edit": _edit_dc("file:///x.py", 0, 0, 3, 0, "")}
    ]
    fake_pool["pylsp-rope"].code_actions = [
        {"title": "Organize imports", "kind": "source.organizeImports",
         "edit": _edit_dc("file:///x.py", 0, 0, 3, 0, "")}
    ]
    fake_pool["basedpyright"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["source.organizeImports"],
    )
    assert merged[0].suppressed_alternatives == []


@pytest.mark.asyncio
async def test_returns_merged_code_action_instances(fake_pool):
    fake_pool["ruff"].code_actions = [
        {"title": "Fix all", "kind": "source.fixAll.ruff",
         "edit": _edit_dc("file:///x.py", 0, 0, 0, 5, "FIXED")}
    ]
    fake_pool["pylsp-rope"].code_actions = []
    fake_pool["basedpyright"].code_actions = []
    coord = MultiServerCoordinator(fake_pool)
    merged = await coord.merge_code_actions(
        file="/tmp/x.py",
        start={"line": 0, "character": 0},
        end={"line": 0, "character": 0},
        only=["source.fixAll"],
    )
    assert all(isinstance(m, MergedCodeAction) for m in merged)
