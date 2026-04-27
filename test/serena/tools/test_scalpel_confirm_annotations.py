"""v1.1 Stream 5 / Leaf 06 Task 2 — confirmation-mode dry-run tests.

Covers the ``ScalpelDryRunComposeTool`` extension (``confirmation_mode='manual'``).
Bypasses the full ``Tool.apply_ex`` lifecycle and calls ``apply`` directly,
matching the pattern in :mod:`test/serena/tools/test_scalpel_reload_plugins`.
Task 3 adds the ``ScalpelConfirmAnnotationsTool`` tests; Task 4 adds the
docstring-cite + auto-registration lint gates in subsequent commits.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.tools.scalpel_primitives import ScalpelDryRunComposeTool
from serena.tools.scalpel_runtime import ScalpelRuntime


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate the ScalpelRuntime singleton + its disk roots between tests."""
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_dry_run_tool(tmp_path: Path) -> ScalpelDryRunComposeTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(tmp_path)
    tool = ScalpelDryRunComposeTool(agent=agent)
    # ``Tool.get_project_root`` is implemented on the agent; pin it via the mock.
    object.__setattr__(tool, "get_project_root", lambda: str(tmp_path))
    return tool


def _make_workspace_edit_with_two_groups(file_a: Path, file_b: Path) -> dict[str, Any]:
    """Build a fake WorkspaceEdit with two ChangeAnnotation groups.

    file_a → 'rename' annotation; file_b → 'extract' annotation. Each file gets
    a one-character insertion so we can verify the filtered apply touches the
    correct subset of files.
    """
    file_a.write_text("AAA\n", encoding="utf-8")
    file_b.write_text("BBB\n", encoding="utf-8")
    return {
        "changeAnnotations": {
            "rename": {"label": "rename", "needsConfirmation": True},
            "extract": {"label": "extract", "needsConfirmation": True},
        },
        "documentChanges": [
            {
                "textDocument": {"uri": file_a.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 0},
                        },
                        "newText": "X",
                        "annotationId": "rename",
                    },
                ],
            },
            {
                "textDocument": {"uri": file_b.as_uri(), "version": None},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {"line": 0, "character": 0},
                        },
                        "newText": "Y",
                        "annotationId": "extract",
                    },
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Task 2 — ScalpelDryRunComposeTool with confirmation_mode='manual'
# ---------------------------------------------------------------------------


def test_dry_run_compose_default_mode_unchanged(tmp_path: Path) -> None:
    """No ``confirmation_mode`` arg means original behaviour: no pending tx."""
    tool = _build_dry_run_tool(tmp_path)
    payload = json.loads(tool.apply(steps=[]))
    assert "awaiting_confirmation" not in payload
    store = ScalpelRuntime.instance().pending_tx_store()
    assert store.get(payload["transaction_id"]) is None


def test_dry_run_compose_manual_mode_persists_pending_tx(tmp_path: Path) -> None:
    """Manual mode short-circuits application + persists a PendingTransaction."""
    tool = _build_dry_run_tool(tmp_path)
    edit = _make_workspace_edit_with_two_groups(
        tmp_path / "a.py", tmp_path / "b.py",
    )
    payload = json.loads(
        tool.apply(steps=[], confirmation_mode="manual", workspace_edit=edit),
    )
    assert payload["awaiting_confirmation"] is True
    tx_id = payload["transaction_id"]
    assert tx_id  # non-empty
    store = ScalpelRuntime.instance().pending_tx_store()
    assert store.has_pending(tx_id)
    pending = store.get(tx_id)
    assert pending is not None
    assert {g.label for g in pending.groups} == {"rename", "extract"}


def test_dry_run_compose_manual_mode_no_annotations_still_persists(
    tmp_path: Path,
) -> None:
    """Even with no annotations, manual mode short-circuits (empty groups tuple)."""
    tool = _build_dry_run_tool(tmp_path)
    payload = json.loads(
        tool.apply(steps=[], confirmation_mode="manual", workspace_edit={}),
    )
    assert payload["awaiting_confirmation"] is True
    pending = ScalpelRuntime.instance().pending_tx_store().get(
        payload["transaction_id"],
    )
    assert pending is not None
    assert pending.groups == ()
