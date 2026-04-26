"""T5 — ScalpelDryRunComposeTool: shadow workspace, per-step delta, TTL."""

from __future__ import annotations

import json
import time
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
    from serena.tools.scalpel_primitives import ScalpelDryRunComposeTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return ScalpelDryRunComposeTool(agent=agent)


def test_tool_name_is_scalpel_dry_run_compose() -> None:
    from serena.tools.scalpel_primitives import ScalpelDryRunComposeTool

    assert ScalpelDryRunComposeTool.get_name_from_cls() == "scalpel_dry_run_compose"


def test_apply_returns_transaction_id_and_5min_ttl(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply(steps=[])
    payload = json.loads(raw)
    assert "transaction_id" in payload
    assert payload["transaction_id"].startswith("txn_")
    now = time.time()
    assert now + 250 < payload["expires_at"] < now + 320


def test_apply_records_per_step_preview(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    steps_payload = [
        {"tool": "scalpel_apply_capability",
         "args": {"capability_id": "x.unknown", "file": "a.py",
                  "range_or_name_path": "x"}},
    ]
    raw = tool.apply(steps=steps_payload)
    payload = json.loads(raw)
    assert len(payload["per_step"]) == 1
    assert payload["per_step"][0]["tool"] == "scalpel_apply_capability"
    assert payload["per_step"][0]["step_index"] == 0


def test_apply_fail_fast_default_aborts_at_first_failure(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    with patch(
        "serena.tools.scalpel_primitives._dry_run_one_step",
    ) as mock_step:
        from serena.tools.scalpel_schemas import (
            DiagnosticsDelta,
            DiagnosticSeverityBreakdown,
            ErrorCode,
            FailureInfo,
            StepPreview,
        )
        zero = DiagnosticSeverityBreakdown()
        mock_step.side_effect = [
            StepPreview(
                step_index=0,
                tool="ok_tool",
                changes=(),
                diagnostics_delta=DiagnosticsDelta(
                    before=zero, after=zero, new_findings=(),
                    severity_breakdown=zero,
                ),
                failure=None,
            ),
            StepPreview(
                step_index=1,
                tool="fail_tool",
                changes=(),
                diagnostics_delta=DiagnosticsDelta(
                    before=zero, after=zero, new_findings=(),
                    severity_breakdown=zero,
                ),
                failure=FailureInfo(
                    stage="dry_run", reason="boom",
                    code=ErrorCode.INTERNAL_ERROR, recoverable=False,
                ),
            ),
            StepPreview(
                step_index=2,
                tool="never_run",
                changes=(),
                diagnostics_delta=DiagnosticsDelta(
                    before=zero, after=zero, new_findings=(),
                    severity_breakdown=zero,
                ),
                failure=None,
            ),
        ]
        raw = tool.apply(
            steps=[
                {"tool": "ok_tool", "args": {}},
                {"tool": "fail_tool", "args": {}},
                {"tool": "never_run", "args": {}},
            ],
            fail_fast=True,
        )
    payload = json.loads(raw)
    assert len(payload["per_step"]) == 2
    assert payload["per_step"][1]["failure"]["code"] == "INTERNAL_ERROR"
    assert any("TRANSACTION_ABORTED" in w for w in payload["warnings"])


def test_apply_fail_fast_false_continues_through_failures(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    with patch(
        "serena.tools.scalpel_primitives._dry_run_one_step",
    ) as mock_step:
        from serena.tools.scalpel_schemas import (
            DiagnosticsDelta,
            DiagnosticSeverityBreakdown,
            ErrorCode,
            FailureInfo,
            StepPreview,
        )
        zero = DiagnosticSeverityBreakdown()
        mock_step.side_effect = [
            StepPreview(
                step_index=0, tool="ok", changes=(),
                diagnostics_delta=DiagnosticsDelta(
                    before=zero, after=zero, new_findings=(),
                    severity_breakdown=zero,
                ), failure=None,
            ),
            StepPreview(
                step_index=1, tool="fail", changes=(),
                diagnostics_delta=DiagnosticsDelta(
                    before=zero, after=zero, new_findings=(),
                    severity_breakdown=zero,
                ),
                failure=FailureInfo(
                    stage="dry_run", reason="boom",
                    code=ErrorCode.INTERNAL_ERROR, recoverable=True,
                ),
            ),
            StepPreview(
                step_index=2, tool="ok2", changes=(),
                diagnostics_delta=DiagnosticsDelta(
                    before=zero, after=zero, new_findings=(),
                    severity_breakdown=zero,
                ), failure=None,
            ),
        ]
        raw = tool.apply(
            steps=[{"tool": "ok", "args": {}},
                   {"tool": "fail", "args": {}},
                   {"tool": "ok2", "args": {}}],
            fail_fast=False,
        )
    payload = json.loads(raw)
    assert len(payload["per_step"]) == 3


def test_apply_invalid_step_payload_returns_invalid_argument(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    raw = tool.apply(steps=[{"missing_tool_field": True}])  # type: ignore[arg-type]
    payload = json.loads(raw)
    assert "warnings" in payload
    assert any("INVALID_ARGUMENT" in w for w in payload["warnings"])
    assert payload["per_step"] == []
