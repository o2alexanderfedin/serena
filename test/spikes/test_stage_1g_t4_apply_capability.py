"""T4 — ApplyCapabilityTool: dispatch, dry-run, workspace boundary."""

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
    from serena.tools.scalpel_primitives import ApplyCapabilityTool

    agent = MagicMock(name="SerenaAgent")
    agent.get_active_project_or_raise.return_value = MagicMock(
        project_root=str(project_root),
    )
    return ApplyCapabilityTool(agent=agent)


def test_tool_name_is_scalpel_apply_capability() -> None:
    from serena.tools.scalpel_primitives import ApplyCapabilityTool

    assert ApplyCapabilityTool.get_name_from_cls() == "apply_capability"


def test_apply_unknown_capability_id_returns_failure(tmp_path: Path) -> None:
    target = tmp_path / "x.py"
    target.write_text("x = 1\n")
    tool = _build_tool(tmp_path)
    raw = tool.apply(
        capability_id="not.a.real.capability",
        file=str(target),
        range_or_name_path="x",
    )
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "CAPABILITY_NOT_AVAILABLE"


def test_apply_rejects_out_of_workspace_by_default(tmp_path: Path) -> None:
    """Default-on workspace-boundary check refuses files outside project_root."""
    out = tmp_path.parent / "elsewhere.py"
    out.write_text("z = 0\n")
    tool = _build_tool(tmp_path)
    # Use a real capability_id so we get past the unknown-id branch.
    from serena.tools.scalpel_runtime import ScalpelRuntime

    cat = ScalpelRuntime.instance().catalog()
    if not cat.records:
        pytest.skip("Capability catalog is empty in this build.")
    cid = cat.records[0].id
    raw = tool.apply(
        capability_id=cid,
        file=str(out),
        range_or_name_path="z",
    )
    payload = json.loads(raw)
    assert payload["applied"] is False
    assert payload["failure"]["code"] == "WORKSPACE_BOUNDARY_VIOLATION"


def test_apply_allow_out_of_workspace_bypasses_boundary_check(tmp_path: Path) -> None:
    """allow_out_of_workspace=True skips the boundary check."""
    out = tmp_path.parent / "elsewhere.py"
    out.write_text("z = 0\n")
    tool = _build_tool(tmp_path)
    from serena.tools.scalpel_runtime import ScalpelRuntime

    cat = ScalpelRuntime.instance().catalog()
    if not cat.records:
        pytest.skip("Capability catalog is empty.")
    cid = cat.records[0].id
    with patch(
        "serena.tools.scalpel_primitives._dispatch_via_coordinator",
    ) as mock_dispatch:
        from serena.tools.scalpel_schemas import (
            DiagnosticsDelta,
            DiagnosticSeverityBreakdown,
            RefactorResult,
        )
        zero = DiagnosticSeverityBreakdown()
        mock_dispatch.return_value = RefactorResult(
            applied=True,
            diagnostics_delta=DiagnosticsDelta(
                before=zero, after=zero, new_findings=(),
                severity_breakdown=zero,
            ),
            checkpoint_id="ckpt_test",
        )
        raw = tool.apply(
            capability_id=cid,
            file=str(out),
            range_or_name_path="z",
            allow_out_of_workspace=True,
        )
    payload = json.loads(raw)
    assert payload["applied"] is True
    assert payload.get("failure") is None
    mock_dispatch.assert_called_once()


def test_apply_dry_run_returns_preview_token_no_checkpoint(tmp_path: Path) -> None:
    target = tmp_path / "y.py"
    target.write_text("y = 2\n")
    tool = _build_tool(tmp_path)
    from serena.tools.scalpel_runtime import ScalpelRuntime

    cat = ScalpelRuntime.instance().catalog()
    if not cat.records:
        pytest.skip("Capability catalog is empty.")
    cid = cat.records[0].id
    with patch(
        "serena.tools.scalpel_primitives._dispatch_via_coordinator",
    ) as mock_dispatch:
        from serena.tools.scalpel_schemas import (
            DiagnosticsDelta,
            DiagnosticSeverityBreakdown,
            RefactorResult,
        )
        zero = DiagnosticSeverityBreakdown()
        mock_dispatch.return_value = RefactorResult(
            applied=False,
            no_op=False,
            diagnostics_delta=DiagnosticsDelta(
                before=zero, after=zero, new_findings=(),
                severity_breakdown=zero,
            ),
            preview_token="pv_xyz",
            checkpoint_id=None,
        )
        raw = tool.apply(
            capability_id=cid,
            file=str(target),
            range_or_name_path="y",
            dry_run=True,
        )
    payload = json.loads(raw)
    assert payload["preview_token"] == "pv_xyz"
    assert payload["checkpoint_id"] is None
    kwargs = mock_dispatch.call_args.kwargs
    assert kwargs["dry_run"] is True
