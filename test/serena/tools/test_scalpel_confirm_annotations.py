"""v1.1 Stream 5 / Leaf 06 Tasks 2-4 — confirmation-mode tool tests.

Covers the ``DryRunComposeTool`` extension (``confirmation_mode='manual'``,
Task 2), the ``ConfirmAnnotationsTool`` apply-only-accepted-groups
workflow (Task 3), and the docstring-cite + MCP auto-registration lint
gates (Task 4). Bypasses the full ``Tool.apply_ex`` lifecycle and calls
``apply`` directly, matching the pattern in
:mod:`test/serena/tools/test_scalpel_reload_plugins`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.tools.scalpel_primitives import (
    ConfirmAnnotationsTool,
    DryRunComposeTool,
)
from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.tools_base import Tool
from serena.util.inspection import iter_subclasses


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


def _build_dry_run_tool(tmp_path: Path) -> DryRunComposeTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(tmp_path)
    tool = DryRunComposeTool(agent=agent)
    # ``Tool.get_project_root`` is implemented on the agent; pin it via the mock.
    object.__setattr__(tool, "get_project_root", lambda: str(tmp_path))
    return tool


def _build_confirm_tool(tmp_path: Path) -> ConfirmAnnotationsTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(tmp_path)
    tool = ConfirmAnnotationsTool(agent=agent)
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
# Task 2 — DryRunComposeTool with confirmation_mode='manual'
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


# ---------------------------------------------------------------------------
# Task 3 — ConfirmAnnotationsTool
# ---------------------------------------------------------------------------


def test_confirm_applies_only_accepted_groups(tmp_path: Path) -> None:
    """Accepting only 'rename' applies that file's edit and skips 'extract'."""
    file_a = tmp_path / "a.py"
    file_b = tmp_path / "b.py"
    edit = _make_workspace_edit_with_two_groups(file_a, file_b)
    dry = _build_dry_run_tool(tmp_path)
    out_dry = json.loads(
        dry.apply(steps=[], confirmation_mode="manual", workspace_edit=edit),
    )
    tx_id = out_dry["transaction_id"]

    confirm = _build_confirm_tool(tmp_path)
    out = json.loads(confirm.apply(transaction_id=tx_id, accept=["rename"]))

    assert out["applied_groups"] == ["rename"]
    assert out["rejected_groups"] == ["extract"]
    # rename group's edit landed; extract group's edit did NOT.
    assert file_a.read_text(encoding="utf-8") == "XAAA\n"
    assert file_b.read_text(encoding="utf-8") == "BBB\n"
    # Pending tx is consumed once confirmation lands.
    assert ScalpelRuntime.instance().pending_tx_store().has_pending(tx_id) is False


def test_confirm_rejects_unknown_transaction_id(tmp_path: Path) -> None:
    """Unknown id returns structured UNKNOWN_TRANSACTION error, not exception."""
    confirm = _build_confirm_tool(tmp_path)
    out = json.loads(confirm.apply(transaction_id="ghost", accept=[]))
    assert out["error_code"] == "UNKNOWN_TRANSACTION"
    assert out["transaction_id"] == "ghost"


def test_confirm_with_empty_accept_rejects_all_groups(tmp_path: Path) -> None:
    """An empty ``accept`` list applies nothing and marks all groups rejected."""
    file_a = tmp_path / "a.py"
    file_b = tmp_path / "b.py"
    edit = _make_workspace_edit_with_two_groups(file_a, file_b)
    dry = _build_dry_run_tool(tmp_path)
    tx_id = json.loads(
        dry.apply(steps=[], confirmation_mode="manual", workspace_edit=edit),
    )["transaction_id"]

    confirm = _build_confirm_tool(tmp_path)
    out = json.loads(confirm.apply(transaction_id=tx_id, accept=[]))

    assert out["applied_groups"] == []
    assert sorted(out["rejected_groups"]) == ["extract", "rename"]
    assert file_a.read_text(encoding="utf-8") == "AAA\n"
    assert file_b.read_text(encoding="utf-8") == "BBB\n"
    # Tx is still consumed — abandon path.
    assert ScalpelRuntime.instance().pending_tx_store().has_pending(tx_id) is False


def test_pending_tx_persists_across_runtime_resets(tmp_path: Path) -> None:
    """Disk-backed: second runtime instance sees the pending tx (Leaf 02)."""
    file_a = tmp_path / "a.py"
    file_b = tmp_path / "b.py"
    edit = _make_workspace_edit_with_two_groups(file_a, file_b)
    dry = _build_dry_run_tool(tmp_path)
    tx_id = json.loads(
        dry.apply(steps=[], confirmation_mode="manual", workspace_edit=edit),
    )["transaction_id"]

    ScalpelRuntime.reset_for_testing()
    # New runtime, same disk root → pending tx survives.
    assert ScalpelRuntime.instance().pending_tx_store().has_pending(tx_id)


# ---------------------------------------------------------------------------
# Task 4 — Documentation cross-reference (lint gate)
# ---------------------------------------------------------------------------


def test_confirm_tool_class_docstring_cites_q4_line_211() -> None:
    """R2: cite §6.3 line 211 specifically; the surrounding paragraph rejects D."""
    doc = ConfirmAnnotationsTool.__doc__ or ""
    pattern = re.compile(
        r"q4-changeannotations-auto-accept\.md\s+§6\.3\s+line\s+211",
    )
    assert pattern.search(doc), (
        "ConfirmAnnotationsTool docstring must cite "
        "'q4-changeannotations-auto-accept.md §6.3 line 211' verbatim "
        "(R2 — line 211 carries the v1.1 endorsement; the paragraph rejects D)."
    )


def test_confirm_tool_appears_in_iter_subclasses() -> None:
    """Auto-registration via ``iter_subclasses(Tool)`` (Stage 1G mechanism)."""
    discovered = {cls.get_name_from_cls() for cls in iter_subclasses(Tool)}
    assert "confirm_annotations" in discovered


def test_confirm_tool_class_name_resolves_to_snake_cased_form() -> None:
    assert (
        ConfirmAnnotationsTool.get_name_from_cls()
        == "confirm_annotations"
    )


def test_confirm_tool_exported_from_tools_package() -> None:
    from serena import tools as tools_pkg

    assert hasattr(tools_pkg, "ConfirmAnnotationsTool")
    assert tools_pkg.ConfirmAnnotationsTool is ConfirmAnnotationsTool
