"""T2 — workspace/applyEdit reverse-request capture.

Proves: (1) handler ACKs `{applied: true, failureReason: null}`, (2) the
WorkspaceEdit payload is appended to pending_apply_edits in arrival order,
(3) pop_pending_apply_edits() drains the buffer.

Pure unit test: bypasses __init__ via __new__, manually populates the
listener-bookkeeping fields the handler reads.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from solidlsp.ls import SolidLanguageServer


@pytest.fixture
def apply_edit_sls(slim_sls: SolidLanguageServer) -> SolidLanguageServer:
    slim_sls._pending_apply_edits = []
    slim_sls._apply_edits_lock = threading.Lock()
    return slim_sls


def test_handler_acks_and_captures(apply_edit_sls: SolidLanguageServer) -> None:
    edit: dict[str, Any] = {"changes": {"file:///foo.py": [{"range": {}, "newText": "x"}]}}
    response = apply_edit_sls._handle_workspace_apply_edit({"edit": edit, "label": "Inline"})
    assert response == {"applied": True, "failureReason": None}
    assert apply_edit_sls._pending_apply_edits == [{"edit": edit, "label": "Inline"}]


def test_pop_drains_in_arrival_order(apply_edit_sls: SolidLanguageServer) -> None:
    apply_edit_sls._handle_workspace_apply_edit({"edit": {"changes": {}}, "label": "a"})
    apply_edit_sls._handle_workspace_apply_edit({"edit": {"changes": {}}, "label": "b"})
    drained = apply_edit_sls.pop_pending_apply_edits()
    assert [p["label"] for p in drained] == ["a", "b"]
    assert apply_edit_sls.pop_pending_apply_edits() == []  # empty after drain


def test_concurrent_capture_is_thread_safe(apply_edit_sls: SolidLanguageServer) -> None:
    """Two threads firing 50 captures each must produce 100 entries (no lost writes)."""
    def burst() -> None:
        for i in range(50):
            apply_edit_sls._handle_workspace_apply_edit({"edit": {"changes": {}}, "label": str(i)})

    threads = [threading.Thread(target=burst), threading.Thread(target=burst)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(apply_edit_sls._pending_apply_edits) == 100
