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


class _ConcreteSLS(SolidLanguageServer):
    """Concrete subclass that satisfies ABC so __new__ succeeds.

    SolidLanguageServer declares ``_start_server`` abstract; Python 3.12+
    enforces ABC at ``__new__`` time, so we must provide a concrete subclass
    even when bypassing __init__.
    """

    def _start_server(self) -> None:  # pragma: no cover - never called in unit tests
        raise NotImplementedError


@pytest.fixture
def slim_sls() -> SolidLanguageServer:
    sls = _ConcreteSLS.__new__(_ConcreteSLS)
    sls._pending_apply_edits = []
    sls._apply_edits_lock = threading.Lock()
    return sls


def test_handler_acks_and_captures(slim_sls: SolidLanguageServer) -> None:
    edit: dict[str, Any] = {"changes": {"file:///foo.py": [{"range": {}, "newText": "x"}]}}
    response = slim_sls._handle_workspace_apply_edit({"edit": edit, "label": "Inline"})
    assert response == {"applied": True, "failureReason": None}
    assert slim_sls._pending_apply_edits == [{"edit": edit, "label": "Inline"}]


def test_pop_drains_in_arrival_order(slim_sls: SolidLanguageServer) -> None:
    slim_sls._handle_workspace_apply_edit({"edit": {"changes": {}}, "label": "a"})
    slim_sls._handle_workspace_apply_edit({"edit": {"changes": {}}, "label": "b"})
    drained = slim_sls.pop_pending_apply_edits()
    assert [p["label"] for p in drained] == ["a", "b"]
    assert slim_sls.pop_pending_apply_edits() == []  # empty after drain


def test_concurrent_capture_is_thread_safe(slim_sls: SolidLanguageServer) -> None:
    """Two threads firing 50 captures each must produce 100 entries (no lost writes)."""
    def burst() -> None:
        for i in range(50):
            slim_sls._handle_workspace_apply_edit({"edit": {"changes": {}}, "label": str(i)})

    threads = [threading.Thread(target=burst), threading.Thread(target=burst)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(slim_sls._pending_apply_edits) == 100
