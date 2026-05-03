"""v1.5 G1 — shared-dispatcher disambiguation policy.

Asserts:
  * Default behavior (title_match=None, no is_preferred): first action wins
    (status quo — does not regress 17 existing callers).
  * is_preferred=True wins over a non-preferred earlier candidate.
  * title_match selects the candidate whose normalized title contains the
    substring (case-insensitive). Wins even over is_preferred.
  * title_match with multiple matching candidates returns the
    MULTIPLE_CANDIDATES envelope (status=skipped, kind, candidates list).
  * title_match with zero matching candidates returns the same envelope
    with reason="no_candidate_matched_title_match".
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from serena.tools.scalpel_facades import (
    _select_candidate_action,
    _dispatch_single_kind_facade,
    _python_dispatch_single_kind,
)


def _action(action_id: str, title: str, *, preferred: bool = False):
    a = MagicMock()
    a.id = action_id
    a.action_id = action_id
    a.title = title
    a.is_preferred = preferred
    a.provenance = "rust-analyzer"
    return a


def test_select_default_returns_first_action():
    actions = [_action("a", "First"), _action("b", "Second")]
    chosen, status = _select_candidate_action(actions, title_match=None)
    assert chosen is actions[0]
    assert status is None


def test_select_is_preferred_wins_over_first():
    actions = [_action("a", "First"), _action("b", "Second", preferred=True)]
    chosen, status = _select_candidate_action(actions, title_match=None)
    assert chosen is actions[1]
    assert status is None


def test_select_title_match_wins_over_is_preferred():
    actions = [
        _action("a", "Change visibility to pub(crate)"),
        _action("b", "Change visibility to pub", preferred=True),
    ]
    chosen, status = _select_candidate_action(
        actions, title_match="pub(crate)",
    )
    assert chosen is actions[0]
    assert status is None


def test_select_title_match_case_insensitive_substring():
    actions = [_action("a", "Implement Display for Foo")]
    chosen, status = _select_candidate_action(actions, title_match="display")
    assert chosen is actions[0]
    assert status is None


def test_select_title_match_ambiguous_returns_envelope():
    actions = [
        _action("a", "Change visibility to pub(crate)"),
        _action("b", "Change visibility to pub(crate) and re-export"),
    ]
    chosen, status = _select_candidate_action(
        actions, title_match="pub(crate)",
    )
    assert chosen is None
    assert status is not None
    assert status["status"] == "skipped"
    assert status["reason"] == "multiple_candidates_matched_title_match"
    candidates = status["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 2


def test_select_title_match_no_match_returns_envelope():
    actions = [_action("a", "Change visibility to pub")]
    chosen, status = _select_candidate_action(
        actions, title_match="pub(crate)",
    )
    assert chosen is None
    assert status is not None
    assert status["reason"] == "no_candidate_matched_title_match"


def test_dispatcher_default_path_unchanged_for_existing_callers(tmp_path):
    """Regression guard: 17 existing callers pass no title_match; their
    behavior must be byte-identical to the pre-G1 behavior — actions[0]
    chosen, edit applied, RefactorResult returned."""
    src = tmp_path / "lib.rs"
    src.write_text("fn x() {}\n")
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _fake_actions(**_kw):
        return [_action("a", "Promote local to constant")]

    fake_coord.merge_code_actions = _fake_actions
    fake_coord.get_action_edit = lambda _aid: {
        "changes": {
            src.as_uri(): [{
                "range": {"start": {"line": 0, "character": 0},
                          "end": {"line": 0, "character": 2}},
                "newText": "FN",
            }],
        },
    }
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = _dispatch_single_kind_facade(
            stage_name="scalpel_test",
            file=str(src),
            position={"line": 0, "character": 0},
            kind="refactor.rewrite.promote_local_to_const",
            project_root=tmp_path,
            dry_run=False,
            language="rust",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    # Real-disk acid test:
    assert src.read_text(encoding="utf-8").startswith("FN")


def test_dispatcher_title_match_routes_to_correct_action(tmp_path):
    src = tmp_path / "lib.rs"
    src.write_text("pub fn x() {}\n")
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _fake_actions(**_kw):
        return [
            _action("a", "Change visibility to pub"),
            _action("b", "Change visibility to pub(crate)"),
        ]

    fake_coord.merge_code_actions = _fake_actions

    def _resolve(aid):
        if aid == "b":
            return {
                "changes": {
                    src.as_uri(): [{
                        "range": {"start": {"line": 0, "character": 0},
                                  "end": {"line": 0, "character": 3}},
                        "newText": "pub(crate)",
                    }],
                },
            }
        return None  # 'a' resolution must NOT be requested.

    fake_coord.get_action_edit = _resolve
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = _dispatch_single_kind_facade(
            stage_name="change_visibility",
            file=str(src),
            position={"line": 0, "character": 0},
            kind="refactor.rewrite.change_visibility",
            project_root=tmp_path,
            dry_run=False,
            language="rust",
            title_match="pub(crate)",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    # The real-disk acid test: the edit that landed is the pub(crate) one.
    assert "pub(crate)" in src.read_text(encoding="utf-8")


def test_dispatcher_title_match_ambiguous_returns_envelope_no_disk_change(tmp_path):
    """When title_match selects ≥2 candidates, the dispatcher returns a
    MULTIPLE_CANDIDATES envelope and DOES NOT mutate disk."""
    src = tmp_path / "lib.rs"
    original = "pub fn x() {}\n"
    src.write_text(original)
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _fake_actions(**_kw):
        return [
            _action("a", "Change visibility to pub(crate)"),
            _action("b", "Change visibility to pub(crate) and re-export"),
        ]

    fake_coord.merge_code_actions = _fake_actions
    fake_coord.get_action_edit = MagicMock()  # MUST NOT be called.

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = _dispatch_single_kind_facade(
            stage_name="change_visibility",
            file=str(src),
            position={"line": 0, "character": 0},
            kind="refactor.rewrite.change_visibility",
            project_root=tmp_path,
            dry_run=False,
            language="rust",
            title_match="pub(crate)",
        )
    payload = json.loads(out)
    assert payload.get("status") == "skipped"
    assert payload["reason"] == "multiple_candidates_matched_title_match"
    # Disk untouched:
    assert src.read_text(encoding="utf-8") == original
    fake_coord.get_action_edit.assert_not_called()


def test_python_dispatcher_title_match_routes_correctly(tmp_path):
    """Mirror of the Rust dispatcher test for ``_python_dispatch_single_kind``."""
    src = tmp_path / "mod.py"
    src.write_text("def helper(): pass\n")
    fake_coord = MagicMock()
    fake_coord.supports_kind.return_value = True

    async def _fake_actions(**_kw):
        return [
            _action("a", "Inline variable"),
            _action("b", "Inline function"),
        ]

    fake_coord.merge_code_actions = _fake_actions

    def _resolve(aid):
        if aid == "b":
            return {
                "changes": {
                    src.as_uri(): [{
                        "range": {"start": {"line": 0, "character": 0},
                                  "end": {"line": 0, "character": 18}},
                        "newText": "INLINED",
                    }],
                },
            }
        return None

    fake_coord.get_action_edit = _resolve
    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = _python_dispatch_single_kind(
            stage_name="use_function",
            file=str(src),
            position={"line": 0, "character": 4},
            kind="refactor.inline",
            project_root=tmp_path,
            dry_run=False,
            title_match="function",
        )
    payload = json.loads(out)
    assert payload["applied"] is True
    assert "INLINED" in src.read_text(encoding="utf-8")
