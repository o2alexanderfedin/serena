"""T8 — execute_command pass-through with applyEdit drain.

Two pure-unit tests with a fake server:
- Standard case: executeCommand returns a response, no reverse-requests
  fire during execution; drained list is empty.
- pylsp-rope-style: server fires workspace/applyEdit reverse-request
  during execution (we simulate by appending directly to the buffer);
  facade returns (response, drained_apply_edits).
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from solidlsp.ls import SolidLanguageServer


@pytest.fixture
def execcmd_sls(slim_sls: SolidLanguageServer) -> SolidLanguageServer:
    """slim_sls + the T2 buffer state execute_command depends on."""
    slim_sls._pending_apply_edits = []
    slim_sls._apply_edits_lock = threading.Lock()
    return slim_sls


def test_execute_command_returns_response(execcmd_sls: SolidLanguageServer) -> None:
    fake_server = MagicMock()
    fake_server.send_request.return_value = {"ok": True}
    execcmd_sls.server = fake_server
    response, drained = execcmd_sls.execute_command(
        "pylsp_rope.refactor.inline", [{"document_uri": "file:///a.py"}]
    )
    args, _kwargs = fake_server.send_request.call_args
    assert args[0] == "workspace/executeCommand"
    assert args[1] == {
        "command": "pylsp_rope.refactor.inline",
        "arguments": [{"document_uri": "file:///a.py"}],
    }
    assert response == {"ok": True}
    assert drained == []


def test_execute_command_drains_captured_apply_edits(execcmd_sls: SolidLanguageServer) -> None:
    fake_server = MagicMock()

    def fake_send(method, params):
        # Simulate the server firing applyEdit DURING execution by appending
        # directly to the buffer (real path: _handle_workspace_apply_edit).
        execcmd_sls._pending_apply_edits.append(
            {"edit": {"changes": {"file:///a.py": []}}, "label": "Inline"}
        )
        return {"ok": True}

    fake_server.send_request.side_effect = fake_send
    execcmd_sls.server = fake_server
    _resp, drained = execcmd_sls.execute_command("pylsp_rope.refactor.inline", [])
    assert len(drained) == 1
    assert drained[0]["label"] == "Inline"


def test_execute_command_omits_arguments_default(execcmd_sls: SolidLanguageServer) -> None:
    """`arguments=None` should send `arguments: []` per LSP convention."""
    fake_server = MagicMock()
    fake_server.send_request.return_value = None
    execcmd_sls.server = fake_server
    _resp, _drained = execcmd_sls.execute_command("rust-analyzer/analyzerStatus")
    args, _kwargs = fake_server.send_request.call_args
    assert args[1] == {"command": "rust-analyzer/analyzerStatus", "arguments": []}
