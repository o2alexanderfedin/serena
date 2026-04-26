"""T8 — ScalpelExecuteCommandTool: typed pass-through with whitelist."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_tool(project_root: Path):  # type: ignore[no-untyped-def]
    from serena.tools.scalpel_primitives import ScalpelExecuteCommandTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return ScalpelExecuteCommandTool(agent=agent)


def test_tool_name_is_scalpel_execute_command() -> None:
    from serena.tools.scalpel_primitives import ScalpelExecuteCommandTool

    assert ScalpelExecuteCommandTool.get_name_from_cls() == "scalpel_execute_command"


def test_apply_unknown_command_returns_capability_not_available(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply(
        command="server.does.not.have.this.command",
        arguments=[],
        language="python",
    )
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "CAPABILITY_NOT_AVAILABLE"


def test_apply_unknown_language_returns_invalid_argument(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply(
        command="anything",
        arguments=[],
        language="cobol",  # type: ignore[arg-type]
    )
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "INVALID_ARGUMENT"


def test_apply_whitelisted_command_invokes_coordinator_broadcast(tmp_path: Path) -> None:
    """A command in the strategy's whitelist is passed through to broadcast."""
    tool = _build_tool(tmp_path)
    with patch(
        "serena.tools.scalpel_primitives._execute_via_coordinator",
    ) as mock_exec:
        from serena.tools.scalpel_schemas import (
            DiagnosticsDelta,
            DiagnosticSeverityBreakdown,
            RefactorResult,
        )
        zero = DiagnosticSeverityBreakdown()
        mock_exec.return_value = RefactorResult(
            applied=True,
            diagnostics_delta=DiagnosticsDelta(
                before=zero, after=zero, new_findings=(),
                severity_breakdown=zero,
            ),
        )
        raw = tool.apply(
            command="pylsp.executeCommand",
            arguments=["a", "b"],
            language="python",
            allow_out_of_workspace=True,
        )
    payload = json.loads(raw)
    assert payload["applied"] is True
    assert payload.get("failure") is None
    mock_exec.assert_called_once()
    kwargs = mock_exec.call_args.kwargs
    assert kwargs["command"] == "pylsp.executeCommand"
    assert kwargs["arguments"] == ("a", "b")


def test_apply_language_inferred_when_not_provided(tmp_path: Path) -> None:
    """If language is None, the tool falls back to a deterministic default."""
    tool = _build_tool(tmp_path)
    raw = tool.apply(command="unknown", arguments=[])
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert "failure" in payload
