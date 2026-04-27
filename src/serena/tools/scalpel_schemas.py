"""Stage 1G — pydantic v2 IO schemas for the 8 always-on primitive tools.

Mirrors §10 (cross-language ``RefactorResult`` family), §5.5 (compose
schemas), §5.1 (catalog descriptors), and §15.4 (10-code ``ErrorCode``
enum). All models are frozen + ``extra="forbid"`` so undeclared fields
raise at construction and instances are immutable. Tools serialise via
``.model_dump_json(indent=2)``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from serena.refactoring.multi_server import ProvenanceLiteral

# --- shared enums -----------------------------------------------------


class ErrorCode(str, Enum):
    """The 10 error codes emitted by the Stage 1G tools (per §15.4)."""

    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    CAPABILITY_NOT_AVAILABLE = "CAPABILITY_NOT_AVAILABLE"
    WORKSPACE_BOUNDARY_VIOLATION = "WORKSPACE_BOUNDARY_VIOLATION"
    PREVIEW_EXPIRED = "PREVIEW_EXPIRED"
    TRANSACTION_ABORTED = "TRANSACTION_ABORTED"
    LSP_TIMEOUT = "LSP_TIMEOUT"
    LSP_NOT_READY = "LSP_NOT_READY"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    ROLLBACK_PARTIAL = "ROLLBACK_PARTIAL"


# --- base config ------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- §10 RefactorResult family ---------------------------------------


class ChangeProvenance(_Frozen):
    """Per-FileChange provenance — which LSP server emitted the change."""

    source: ProvenanceLiteral
    workspace_boundary_check: bool = True


class Hunk(_Frozen):
    """One contiguous edit chunk inside a FileChange."""

    start_line: int
    end_line: int
    new_text: str


class FileChange(_Frozen):
    """One on-disk file change in a RefactorResult."""

    path: str
    kind: Literal["create", "modify", "delete"]
    hunks: tuple[Hunk, ...] = ()
    provenance: ChangeProvenance


class DiagnosticSeverityBreakdown(_Frozen):
    """Counts per LSP DiagnosticSeverity (1=Error, 2=Warning, 3=Info, 4=Hint)."""

    error: int = 0
    warning: int = 0
    information: int = 0
    hint: int = 0


class _Diagnostic(_Frozen):
    """Minimal LSP Diagnostic projection used inside DiagnosticsDelta."""

    file: str
    line: int
    character: int
    severity: int
    code: str | None
    message: str
    source: str | None


class DiagnosticsDelta(_Frozen):
    """Before/after counts + new findings for a single refactor application."""

    before: DiagnosticSeverityBreakdown
    after: DiagnosticSeverityBreakdown
    new_findings: tuple[_Diagnostic, ...] = ()
    severity_breakdown: DiagnosticSeverityBreakdown


class _LanguageFinding(_Frozen):
    """Per-language finding the standard severity breakdown can't carry."""

    code: str
    message: str
    locations: tuple[dict[str, Any], ...] = ()
    related: tuple[str, ...] = ()


class ResolvedSymbol(_Frozen):
    """One name-path -> resolved-symbol mapping in a RefactorResult."""

    requested: str
    resolved: str
    kind: str


class FailureInfo(_Frozen):
    """Structured failure payload (one of the 10 ErrorCodes)."""

    stage: str
    symbol: str | None = None
    reason: str
    code: ErrorCode
    recoverable: bool = False
    candidates: tuple[str, ...] = ()
    failed_step_index: int | None = None


class LspOpStat(_Frozen):
    """One LSP-method × server timing record for observability."""

    method: str
    server: str
    count: int
    total_ms: int


class RefactorResult(_Frozen):
    """Cross-language result of one refactor application (§10)."""

    applied: bool
    no_op: bool = False
    changes: tuple[FileChange, ...] = ()
    diagnostics_delta: DiagnosticsDelta
    language_findings: tuple[_LanguageFinding, ...] = ()
    checkpoint_id: str | None = None
    transaction_id: str | None = None
    preview_token: str | None = None
    resolved_symbols: tuple[ResolvedSymbol, ...] = ()
    warnings: tuple[str, ...] = ()
    failure: FailureInfo | None = None
    lsp_ops: tuple[LspOpStat, ...] = ()
    duration_ms: int = 0
    language_options: dict[str, Any] = Field(default_factory=dict)


class TransactionResult(_Frozen):
    """Cross-step aggregate over a transaction (commit or rollback)."""

    transaction_id: str
    per_step: tuple[RefactorResult, ...] = ()
    aggregated_diagnostics_delta: DiagnosticsDelta
    aggregated_language_findings: tuple[_LanguageFinding, ...] = ()
    duration_ms: int = 0
    rules_fired: tuple[str, ...] = ()
    rolled_back: bool = False
    remaining_checkpoint_ids: tuple[str, ...] = ()


# --- §5.5 compose schemas --------------------------------------------


class ComposeStep(_Frozen):
    """One step in a dry-run compose chain."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class StepPreview(_Frozen):
    """Per-step preview emitted by dry_run_compose."""

    step_index: int
    tool: str
    changes: tuple[FileChange, ...] = ()
    diagnostics_delta: DiagnosticsDelta
    failure: FailureInfo | None = None


class ComposeResult(_Frozen):
    """Result of a dry_run_compose invocation."""

    transaction_id: str
    per_step: tuple[StepPreview, ...] = ()
    aggregated_changes: tuple[FileChange, ...] = ()
    aggregated_diagnostics_delta: DiagnosticsDelta
    expires_at: float
    warnings: tuple[str, ...] = ()


# --- §10 WorkspaceHealth family --------------------------------------


class ServerHealth(_Frozen):
    """One LSP server's runtime health snapshot."""

    server_id: str
    version: str
    pid: int | None = None
    rss_mb: int | None = None
    capabilities_advertised: tuple[str, ...] = ()


class LanguageHealth(_Frozen):
    """Aggregated health across all servers for one language."""

    language: str
    indexing_state: Literal["indexing", "ready", "failed", "not_started"]
    indexing_progress: str | None = None
    servers: tuple[ServerHealth, ...] = ()
    capabilities_count: int = 0
    dynamic_capabilities: tuple[str, ...] = ()
    estimated_wait_ms: int | None = None
    capability_catalog_hash: str = ""


class WorkspaceHealth(_Frozen):
    """Workspace-wide health probe response."""

    project_root: str
    languages: dict[str, LanguageHealth] = Field(default_factory=dict)


# --- §5.1 catalog descriptors ----------------------------------------


class CapabilityDescriptor(_Frozen):
    """One row of the capabilities_list response."""

    capability_id: str
    title: str
    language: Literal["rust", "python"]
    kind: str
    source_server: ProvenanceLiteral
    preferred_facade: str | None = None


class CapabilityFullDescriptor(_Frozen):
    """Full schema returned by capability_describe."""

    capability_id: str
    title: str
    language: Literal["rust", "python"]
    kind: str
    source_server: ProvenanceLiteral
    preferred_facade: str | None = None
    params_schema: dict[str, Any] = Field(default_factory=dict)
    extension_allow_list: tuple[str, ...] = ()
    description: str = ""


# --- tool-input arg models -------------------------------------------


class ApplyCapabilityArgs(_Frozen):
    """Validated input for ScalpelApplyCapabilityTool.apply."""

    capability_id: str
    file: str
    range_or_name_path: str | dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    preview_token: str | None = None
    allow_out_of_workspace: bool = False


class ExecuteCommandArgs(_Frozen):
    """Validated input for ScalpelExecuteCommandTool.apply."""

    command: str
    arguments: tuple[Any, ...] = ()
    language: Literal["rust", "python"] | None = None
    allow_out_of_workspace: bool = False


__all__ = [
    "ApplyCapabilityArgs",
    "CapabilityDescriptor",
    "CapabilityFullDescriptor",
    "ChangeProvenance",
    "ComposeResult",
    "ComposeStep",
    "DiagnosticSeverityBreakdown",
    "DiagnosticsDelta",
    "ErrorCode",
    "ExecuteCommandArgs",
    "FailureInfo",
    "FileChange",
    "Hunk",
    "LanguageHealth",
    "LspOpStat",
    "RefactorResult",
    "ResolvedSymbol",
    "ServerHealth",
    "StepPreview",
    "TransactionResult",
    "WorkspaceHealth",
]
