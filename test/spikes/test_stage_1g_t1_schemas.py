"""T1 — pydantic v2 IO schemas for the Stage 1G primitive tools."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError


def test_all_schemas_import() -> None:
    from serena.tools.scalpel_schemas import (
        ApplyCapabilityArgs,
        CapabilityDescriptor,
        CapabilityFullDescriptor,
        ChangeProvenance,
        ComposeResult,
        ComposeStep,
        DiagnosticSeverityBreakdown,
        DiagnosticsDelta,
        ErrorCode,
        ExecuteCommandArgs,
        FailureInfo,
        FileChange,
        Hunk,
        LanguageHealth,
        LspOpStat,
        RefactorResult,
        ResolvedSymbol,
        ServerHealth,
        StepPreview,
        TransactionResult,
        WorkspaceHealth,
    )

    # Reference each symbol so the import isn't flagged unused.
    for sym in (
        ApplyCapabilityArgs,
        CapabilityDescriptor,
        CapabilityFullDescriptor,
        ChangeProvenance,
        ComposeResult,
        ComposeStep,
        DiagnosticSeverityBreakdown,
        DiagnosticsDelta,
        ErrorCode,
        ExecuteCommandArgs,
        FailureInfo,
        FileChange,
        Hunk,
        LanguageHealth,
        LspOpStat,
        RefactorResult,
        ResolvedSymbol,
        ServerHealth,
        StepPreview,
        TransactionResult,
        WorkspaceHealth,
    ):
        assert sym is not None


def test_diagnostic_severity_breakdown_round_trip() -> None:
    from serena.tools.scalpel_schemas import DiagnosticSeverityBreakdown

    sev = DiagnosticSeverityBreakdown(error=1, warning=2, information=3, hint=4)
    j = sev.model_dump_json()
    assert json.loads(j) == {"error": 1, "warning": 2, "information": 3, "hint": 4}


def test_change_provenance_source_is_closed_literal() -> None:
    from serena.tools.scalpel_schemas import ChangeProvenance

    ChangeProvenance(source="rust-analyzer", workspace_boundary_check=True)
    with pytest.raises(ValidationError):
        ChangeProvenance.model_validate(
            {"source": "not-a-server", "workspace_boundary_check": True}
        )


def test_error_code_enum_membership() -> None:
    from serena.tools.scalpel_schemas import ErrorCode

    expected = {
        "SYMBOL_NOT_FOUND",
        "CAPABILITY_NOT_AVAILABLE",
        "WORKSPACE_BOUNDARY_VIOLATION",
        "PREVIEW_EXPIRED",
        "TRANSACTION_ABORTED",
        "LSP_TIMEOUT",
        "LSP_NOT_READY",
        "INVALID_ARGUMENT",
        "INTERNAL_ERROR",
        "ROLLBACK_PARTIAL",
        # v1.5 G1: shared-dispatcher disambiguation envelope.
        "MULTIPLE_CANDIDATES",
    }
    assert {e.value for e in ErrorCode} == expected


def test_apply_capability_args_extra_forbid() -> None:
    from serena.tools.scalpel_schemas import ApplyCapabilityArgs

    args = ApplyCapabilityArgs(
        capability_id="rust.refactor.extract.module",
        file="crates/foo/src/lib.rs",
        range_or_name_path="Engine",
        params={},
        dry_run=False,
        preview_token=None,
        allow_out_of_workspace=False,
    )
    assert args.capability_id == "rust.refactor.extract.module"
    with pytest.raises(ValidationError):
        ApplyCapabilityArgs.model_validate(
            {
                "capability_id": "x",
                "file": "y",
                "range_or_name_path": "z",
                "unknown_field": 42,
            }
        )


def test_compose_step_payload_shape() -> None:
    from serena.tools.scalpel_schemas import ComposeStep

    step = ComposeStep(tool="split_file", args={"file": "a.py", "groups": {}})
    assert step.tool == "split_file"
    assert step.args == {"file": "a.py", "groups": {}}


def test_refactor_result_minimal() -> None:
    from serena.tools.scalpel_schemas import (
        DiagnosticSeverityBreakdown,
        DiagnosticsDelta,
        RefactorResult,
    )

    zero = DiagnosticSeverityBreakdown(error=0, warning=0, information=0, hint=0)
    res = RefactorResult(
        applied=True,
        no_op=False,
        changes=(),
        diagnostics_delta=DiagnosticsDelta(
            before=zero, after=zero, new_findings=(), severity_breakdown=zero,
        ),
        language_findings=(),
        checkpoint_id="ckpt_xyz",
        transaction_id=None,
        preview_token=None,
        resolved_symbols=(),
        warnings=(),
        failure=None,
        lsp_ops=(),
        duration_ms=12,
        language_options={},
    )
    assert res.applied
    assert res.checkpoint_id == "ckpt_xyz"
    assert json.loads(res.model_dump_json())["applied"] is True


def test_refactor_result_is_frozen() -> None:
    from serena.tools.scalpel_schemas import (
        DiagnosticSeverityBreakdown,
        DiagnosticsDelta,
        RefactorResult,
    )

    zero = DiagnosticSeverityBreakdown(error=0, warning=0, information=0, hint=0)
    res = RefactorResult(
        applied=True,
        diagnostics_delta=DiagnosticsDelta(
            before=zero, after=zero, new_findings=(), severity_breakdown=zero,
        ),
        checkpoint_id="ckpt_xyz",
    )
    with pytest.raises(ValidationError):
        res.applied = False  # type: ignore[misc]


def test_workspace_health_aggregates_languages() -> None:
    from serena.tools.scalpel_schemas import (
        LanguageHealth,
        ServerHealth,
        WorkspaceHealth,
    )

    server = ServerHealth(
        server_id="rust-analyzer",
        version="0.3.18xx",
        pid=1234,
        rss_mb=512,
        capabilities_advertised=("refactor.extract", "quickfix"),
    )
    lang = LanguageHealth(
        language="rust",
        indexing_state="ready",
        indexing_progress=None,
        servers=(server,),
        capabilities_count=158,
        estimated_wait_ms=None,
        capability_catalog_hash="sha256:abc",
    )
    wh = WorkspaceHealth(project_root="/tmp/repo", languages={"rust": lang})
    assert wh.languages["rust"].servers[0].pid == 1234
