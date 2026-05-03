"""v1.6 PR 3 / Plan 2 — Fix apply_capability dispatcher.

RED tests:
1. ``test_dispatch_capability_not_available_returns_envelope`` — when
   ``coord.supports_kind(...)`` returns False, the dispatcher MUST short-circuit
   with a CAPABILITY_NOT_AVAILABLE failure envelope (NEW gate).
2. ``test_dispatch_records_resolved_edit_not_empty_changes`` — the recorded
   checkpoint's ``applied`` field MUST equal the resolved ``WorkspaceEdit``
   (not the lying ``{"changes": {}}``).
3. ``test_dispatch_no_actions_returns_failure_unmodified_disk`` — empty
   coordinator action list yields ``applied=False`` /
   ``failure.code=="SYMBOL_NOT_FOUND"`` and never touches disk.
4. ``test_dispatch_dry_run_skips_apply_and_returns_preview_token`` — when
   ``dry_run=True`` the apply path is NOT exercised; ``preview_token`` is
   non-empty.
5. ``test_dispatch_resolve_failure_records_no_op_with_warning`` — when the
   action resolves to ``None`` (legacy fake / untracked id), the dispatcher
   surfaces ``applied=False`` / ``no_op=True``.

Plan source: docs/superpowers/plans/2026-04-29-stub-facade-fix/IMPLEMENTATION-PLANS.md  Plan 2
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from serena.refactoring.checkpoints import CheckpointStore
from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _isolate_runtime() -> Iterator[None]:
    """Reset the ScalpelRuntime singleton + override its checkpoint store
    with an in-memory one (no disk persistence) so tests are hermetic."""
    ScalpelRuntime.reset_for_testing()
    inst = ScalpelRuntime.instance()
    inst._checkpoint_store = CheckpointStore(disk_root=None)
    yield
    ScalpelRuntime.reset_for_testing()


def _build_tool(project_root: Path):  # type: ignore[no-untyped-def]
    from serena.tools.scalpel_primitives import ApplyCapabilityTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return ApplyCapabilityTool(agent=agent)


def _first_python_capability_id() -> str:
    cat = ScalpelRuntime.instance().catalog()
    for rec in cat.records:
        if rec.language == "python":
            return rec.id
    pytest.skip("No python capabilities registered.")


class _FakeAction:
    def __init__(self, action_id: str) -> None:
        self.id = action_id


class _FakeCoordinator:
    """Test double covering the trio the dispatcher calls.

    - ``supports_kind(language, kind)`` — gate (Tier-1 in production).
    - ``merge_code_actions(...)`` — async; returns the prebuilt action list.
    - ``get_action_edit(aid)`` — needed by ``_resolve_winner_edit``.
    """

    def __init__(
        self,
        *,
        supports: bool = True,
        actions: list[Any] | None = None,
        edits: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._supports = supports
        self._actions = actions or []
        self._edits = edits or {}

    def supports_kind(self, language: str, kind: str) -> bool:  # noqa: ARG002
        return self._supports

    async def merge_code_actions(  # noqa: D401 — async to match real signature
        self,
        *,
        file: str,  # noqa: ARG002
        start: dict[str, int],  # noqa: ARG002
        end: dict[str, int],  # noqa: ARG002
        only: list[str] | None = None,  # noqa: ARG002
    ) -> list[Any]:
        return list(self._actions)

    def get_action_edit(self, aid: str) -> dict[str, Any] | None:
        return self._edits.get(aid)


def _install_fake_coordinator(coord: _FakeCoordinator) -> Any:
    """Patch ``ScalpelRuntime.coordinator_for`` to return ``coord``."""
    return patch.object(
        ScalpelRuntime,
        "coordinator_for",
        return_value=coord,
    )


# ---------------------------------------------------------------------------
# RED 1 — supports_kind=False ⇒ CAPABILITY_NOT_AVAILABLE
# ---------------------------------------------------------------------------


def test_dispatch_capability_not_available_returns_envelope(tmp_path: Path) -> None:
    target = tmp_path / "x.py"
    target.write_text("x = 1\n", encoding="utf-8")
    tool = _build_tool(tmp_path)
    cid = _first_python_capability_id()
    coord = _FakeCoordinator(supports=False, actions=[])
    with _install_fake_coordinator(coord):
        raw = tool.apply(
            capability_id=cid,
            file=str(target),
            range_or_name_path={"start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0}},
        )
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "CAPABILITY_NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# RED 2 — recorded checkpoint carries the resolved WorkspaceEdit
# ---------------------------------------------------------------------------


def test_dispatch_records_resolved_edit_not_empty_changes(tmp_path: Path) -> None:
    target = tmp_path / "lib.py"
    target.write_text("ALPHA\n", encoding="utf-8")
    uri = target.as_uri()
    edit: dict[str, Any] = {
        "changes": {
            uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "BETA",
                }
            ]
        }
    }
    action = _FakeAction("a1")
    coord = _FakeCoordinator(
        supports=True, actions=[action], edits={"a1": edit},
    )
    tool = _build_tool(tmp_path)
    cid = _first_python_capability_id()
    with _install_fake_coordinator(coord):
        raw = tool.apply(
            capability_id=cid,
            file=str(target),
            range_or_name_path={"start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0}},
        )
    payload = json.loads(raw)
    assert payload["applied"] is True
    assert payload["checkpoint_id"]
    ckpt = ScalpelRuntime.instance().checkpoint_store().get(payload["checkpoint_id"])
    assert ckpt is not None
    assert ckpt.applied == edit
    assert ckpt.applied != {"changes": {}}


# ---------------------------------------------------------------------------
# RED 3 — no actions ⇒ SYMBOL_NOT_FOUND + disk untouched
# ---------------------------------------------------------------------------


def test_dispatch_no_actions_returns_failure_unmodified_disk(tmp_path: Path) -> None:
    target = tmp_path / "y.py"
    original = "y = 2\n"
    target.write_text(original, encoding="utf-8")
    tool = _build_tool(tmp_path)
    cid = _first_python_capability_id()
    coord = _FakeCoordinator(supports=True, actions=[])
    with _install_fake_coordinator(coord):
        raw = tool.apply(
            capability_id=cid,
            file=str(target),
            range_or_name_path={"start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0}},
        )
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "SYMBOL_NOT_FOUND"
    # Disk untouched.
    assert target.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# RED 4 — dry_run ⇒ no apply, preview_token returned
# ---------------------------------------------------------------------------


def test_dispatch_dry_run_skips_apply_and_returns_preview_token(
    tmp_path: Path,
) -> None:
    target = tmp_path / "z.py"
    original = "z = 3\n"
    target.write_text(original, encoding="utf-8")
    uri = target.as_uri()
    edit: dict[str, Any] = {
        "changes": {
            uri: [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "ZZZZZ",
                }
            ]
        }
    }
    action = _FakeAction("a1")
    coord = _FakeCoordinator(
        supports=True, actions=[action], edits={"a1": edit},
    )
    tool = _build_tool(tmp_path)
    cid = _first_python_capability_id()
    with _install_fake_coordinator(coord), patch(
        "serena.tools.scalpel_primitives.apply_action_and_checkpoint",
    ) as mock_apply:
        raw = tool.apply(
            capability_id=cid,
            file=str(target),
            range_or_name_path={"start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0}},
            dry_run=True,
        )
    payload = json.loads(raw)
    # Preview token returned; checkpoint NOT created.
    assert payload["preview_token"]
    assert payload["applied"] is False
    # Apply helper MUST NOT be invoked in dry_run mode.
    mock_apply.assert_not_called()
    # Disk untouched.
    assert target.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# RED 5 — resolve returns None ⇒ no_op=True, applied=False
# ---------------------------------------------------------------------------


def test_dispatch_resolve_failure_records_no_op_with_warning(
    tmp_path: Path,
) -> None:
    target = tmp_path / "lib2.py"
    target.write_text("ALPHA\n", encoding="utf-8")
    # Action whose id doesn't appear in the coord's edits map ⇒ resolve None.
    action = _FakeAction("missing_id")
    coord = _FakeCoordinator(
        supports=True, actions=[action], edits={},
    )
    tool = _build_tool(tmp_path)
    cid = _first_python_capability_id()
    with _install_fake_coordinator(coord):
        raw = tool.apply(
            capability_id=cid,
            file=str(target),
            range_or_name_path={"start": {"line": 0, "character": 0},
                                "end": {"line": 0, "character": 0}},
        )
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["no_op"] is True
    # Disk untouched (empty-edit fallback inside apply_action_and_checkpoint
    # writes nothing).
    assert target.read_text(encoding="utf-8") == "ALPHA\n"
